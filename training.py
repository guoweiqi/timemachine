import argparse
import time
import numpy as np
import unittest
import ctypes
import random
import tensorflow as tf

from openeye import oechem
from openeye.oechem import OEMol, OEParseSmiles, OEAddExplicitHydrogens, OEGetIsotopicWeight, OEGetAverageWeight
from openeye import oeomega
from openeye.oechem import OEFloatArray

from openforcefield.utils import get_data_filename, generateTopologyFromOEMol
from openforcefield.typing.engines.smirnoff import get_molecule_parameterIDs, ForceField

from timemachine import observable
from timemachine import minimizer
from timemachine.constants import BOLTZ
from timemachine import system_builder
from timemachine.cpu_functionals import custom_ops

from simtk import openmm

def get_abc_coefficents(
    masses,
    dt,
    friction,
    temperature):
    """
    Get a,b,c coefficients of the integrator.
    """
    vscale = np.exp(-dt*friction)
    if friction == 0:
        fscale = dt
    else:
        fscale = (1-vscale)/friction

    kT = BOLTZ * temperature
    nscale = np.sqrt(kT*(1-vscale*vscale)) # noise scale
    invMasses = (1.0/masses).reshape((-1, 1))
    sqrtInvMasses = np.sqrt(invMasses)

    coeff_a = vscale
    coeff_bs = fscale*invMasses
    coeff_cs = nscale*sqrtInvMasses

    return coeff_a, coeff_bs, coeff_cs

def estimate_buffer_size(epsilon, coeff_a):
    """
    Estimate optimal size of the buffer to achieve convergence
    """
    return np.int64(np.log(epsilon)/np.log(coeff_a)+1)


def get_masses(mol):
    masses = []
    for atom in mol.GetAtoms():
        elem = atom.GetAtomicNum()
        mass = atom.GetIsotope()
        masses.append(OEGetIsotopicWeight(elem, mass))

    return np.array(masses)

def mol_coords_to_numpy_array(mol):
    coords = OEFloatArray(mol.GetMaxAtomIdx() * 3)
    mol.GetCoords(coords)
    arr = np.ctypeslib.as_array(ctypes.cast(int(coords.PtrCast()), ctypes.POINTER(ctypes.c_float)), shape=(len(coords),))
    return np.array(arr.reshape((-1, 3)))

def write_xyz(ofs, mol, coords):
    mol.SetCoords(OEFloatArray(coords.reshape(-1)))
    oechem.OEWriteMolecule(ofs, mol)

def initialize_system(
    dt=0.001,
    temperature=100,
    forcefield_file='forcefield/smirnoff99Frosst.offxml',
    smiles="C1CCCCC1"):

    mol = OEMol()
    # OEParseSmiles(mol, 'CCOCCSCC')
    # OEParseSmiles(mol, 'c1ccccc1')
    OEParseSmiles(mol, smiles)
    # OEParseSmiles(mol, 'C([C@@H]1[C@H]([C@@H]([C@H](C(O1)O)O)O)O)O')
    OEAddExplicitHydrogens(mol)
    masses = get_masses(mol)
    num_atoms = mol.NumAtoms()

    topology = generateTopologyFromOEMol(mol)

    ff = ForceField(get_data_filename(forcefield_file))

    nrgs, total_params, offsets = system_builder.construct_energies(ff, mol, False)

    # dt = 0.0025
    # friction = 10.0
    # temperature = 300

    # gradient descent
    dt = dt
    friction = 10.0
    temperature = temperature

    a,b,c = get_abc_coefficents(masses, dt, friction, temperature)

    buf_size = estimate_buffer_size(1e-10, a)

    print("BUFFER SIZE", buf_size)
    omegaOpts = oeomega.OEOmegaOptions()
    omegaOpts.SetMaxConfs(1)
    omega = oeomega.OEOmega(omegaOpts)
    omega.SetStrictStereo(False)

    if not omega(mol):
        assert 0

    x0 = mol_coords_to_numpy_array(mol)/10


    intg = custom_ops.Integrator_double(
        dt,
        buf_size,
        num_atoms,
        total_params,
        a,
        b,
        c
    )

    context = custom_ops.Context_double(
        nrgs,
        intg
    )

    x0 = minimizer.minimize_newton_cg(nrgs, x0, total_params)

    return nrgs, offsets, intg, context, x0, total_params

def run_once(nrgs, context, intg, x0, n_steps, total_params, ksize):
    x0 = minimizer.minimize_newton_cg(nrgs, x0, total_params)
    origin = np.sum(x0, axis=0)/x0.shape[0]
    num_atoms = x0.shape[0]
    num_steps = n_steps
    # ofs = oechem.oemolostream("new_frames.xyz")
    # ofs.SetFormat(oechem.OEFormat_XYZ)

    intg.reset()
    intg.set_coordinates(x0.reshape(-1).tolist())
    intg.set_velocities(np.zeros_like(x0).reshape(-1).tolist())

    start_time = time.time()

    k = ksize
    reservoir = []

    for step in range(n_steps):
        # coords = intg.get_coordinates()
        # dxdps = intg.get_dxdp()
        # reservoir.append((np.array(coords).reshape((num_atoms, 3)), np.array(dxdps).reshape((total_params, num_atoms, 3))))
        if step < k:
            coords = intg.get_coordinates()
            dxdps = intg.get_dxdp()
            reservoir.append((np.array(coords).reshape((num_atoms, 3)), np.array(dxdps).reshape((total_params, num_atoms, 3))))
        else:
            j = random.randint(0, step)
            if j < k:
                coords = intg.get_coordinates()
                dxdps = intg.get_dxdp()
                reservoir[j] = (np.array(coords).reshape((num_atoms, 3)), np.array(dxdps).reshape((total_params, num_atoms, 3)))
        context.step()

    confs = []
    for r in reservoir:
        confs.append(r[0])
    confs = np.array(confs)

    dxdps = []
    for r in reservoir:
        dxdps.append(r[1])
    dxdps = np.array(dxdps)

    return confs, dxdps


def test_mol(smiles):


    nrgs1, offsets1, intg1, context1, init_x_1, total_params_1 = initialize_system(dt=0.001, temperature=20, forcefield_file='forcefield/smirnoff99Frosst.offxml')

    # generate the observable
    print("generating observable")
    ksize = 500
    confs1, _ = run_once(nrgs1, context1, intg1, init_x_1, 40000, total_params_1, ksize) 
    x1 = tf.convert_to_tensor(confs1)
    obs1_rij = observable.sorted_squared_distances(x1)

    # train this secondary system
    print("starting training...")
    bond_learning_rate = np.array([[0.1, 0.0001]])
    angle_learning_rate = np.array([[0.01, 0.001]])
    torsion_learning_rate = np.array([[0.01, 0.001, 0.0]])
    lj_learning_rate = np.array([[0.000, 0.000]])

    nrgs0, offsets0, intg0, context0, init_x_0, total_params_0 = initialize_system(dt=0.001, temperature=20, forcefield_file='forcefield/smirnoff99Frosst_perturbed.offxml')

    for epoch in range(5000): 

        print("starting epoch", epoch)
        confs0, dxdp0 = run_once(nrgs0, context0, intg0, init_x_0, 40000, total_params_0, ksize)
        x0 = tf.convert_to_tensor(confs0)
        obs0_rij = observable.sorted_squared_distances(x0)
        loss = tf.sqrt(tf.reduce_sum(tf.pow(obs0_rij - obs1_rij, 2))/ksize) # RMSE
        x0_grads = tf.gradients(loss, x0)[0]

        config = tf.ConfigProto()
        config.gpu_options.allow_growth=True
        sess = tf.Session()
        np_loss, x0g = sess.run([loss, x0_grads])
        # np_loss = sess.run(loss)

        print("------------------LOSS", np_loss)
        # print("x0g shape", x0g.shape)
        # assert 0
        x0g = np.expand_dims(x0g, 1) # [B, 1, N, 3]
        res = np.multiply(x0g, dxdp0) # dL/dx * dx/dp [B, P, N, 3]

        dLdp = np.sum(res, axis=(0,2,3))

        for dparams, nrg in zip(np.split(dLdp, offsets0)[1:], nrgs0):
            if isinstance(nrg, custom_ops.HarmonicBondGPU_double):
                cp = nrg.get_params()
                dp = bond_learning_rate * dparams.reshape((-1, 2))
                print("BOND PARAMS", cp)
                print("BOND CONSTANTS, LENGTHS", dp)
                nrg.set_params(cp - dp.reshape(-1))
            elif isinstance(nrg, custom_ops.HarmonicAngleGPU_double):
                dp = angle_learning_rate * dparams.reshape((-1, 2))
                print("ANGLE CONSTANTS, ANGLES", dp)
            elif isinstance(nrg, custom_ops.PeriodicTorsionGPU_double):
                dp = torsion_learning_rate * dparams.reshape((-1, 3))
                print("TORSION CONSTANTS, PERIODS, PHASES", dp)
            elif isinstance(nrg, custom_ops.LennardJonesGPU_double):
                dp = lj_learning_rate * dparams.reshape((-1, 2))
                print("LJ SIG, EPS", dp)
            else:
                assert 0


            
            # nrg.set_params(cp - dp.reshape(-1))
            # nrg.set_params(cp)

    assert 0

    for step in range(num_steps):

        if step % 500 == 0:
            # print(step)
            coords = np.array(intg.get_coordinates()).reshape((-1, 3))
            print(coords)
            center = np.sum(coords, axis=0)/coords.shape[0]

            dto = np.sqrt(np.sum(np.power(center - origin, 2)))
            velocities = np.array(intg.get_velocities()).reshape((-1, 3))
            net_mass = np.sum(masses)
            # nv = np.sum(np.expand_dims(np.array(masses), axis=-1)*velocities, axis=0)
            nv = np.sum(np.expand_dims(np.array(masses),axis=-1)*velocities, axis=0)
            # assert 0
            cc_bond_length = np.sqrt(np.sum(np.power(coords[0,: ] - coords[1,:], 2)))

            write_xyz(ofs, mol, np.array(coords)*10)

            dxdp = np.array(intg.get_dxdp()).reshape((total_params, num_atoms, 3))
            amax, amin = np.amax(dxdp), np.amin(dxdp)
            print(step, "\tdto\t", dto, "\tnv\t", nv, "\tcc_bond_length\t", cc_bond_length, "\tamax/amin", amax, "\t", amin)

            segments = np.split(dxdp, offsets)[1:]
            for grads, force in zip(segments, nrgs):
                # print(force)
                if isinstance(force, custom_ops.HarmonicBondGPU_double):
                    grads = grads.reshape((-1, 2, num_atoms, 3))
                    print("Bond Constants:", np.amax(grads[:, 0, :, :]), np.amin(grads[:, 0, :, :]))
                    print("Bond Lengths:", np.amax(grads[:, 1, :, :]), np.amin(grads[:, 1, :, :]))
                    # print(grads[:, 1, :, :])
                elif isinstance(force, custom_ops.HarmonicAngleGPU_double):
                    grads = grads.reshape((-1, 2, num_atoms, 3))
                    print("Angle Constants:", np.amax(grads[:, 0, :, :]), np.amin(grads[:, 0, :, :]))
                    # print(grads[:, 0, :, :])
                    print("Angle Radians:", np.amax(grads[:, 1, :, :]), np.amin(grads[:, 1, :, :]))
                    # print(grads[:, 1, :, :])
                elif isinstance(force, custom_ops.PeriodicTorsionGPU_double):
                    grads = grads.reshape((-1, 3, num_atoms, 3))
                    print("Torsion Constants:", np.amax(grads[:, 0, :, :]), np.amin(grads[:, 0, :, :]))
                    print("Torsion Phase:",  np.amax(grads[:, 1, :, :]), np.amin(grads[:, 1, :, :]))
                    print("Torsion Periods:",  np.amax(grads[:, 2, :, :]), np.amin(grads[:, 2, :, :]))
                elif isinstance(force, custom_ops.LennardJonesGPU_double):
                    grads = grads.reshape((-1, 2, num_atoms, 3))
                    print("LJ sigma:", np.amax(grads[:, 0, :, :]), np.amin(grads[:, 0, :, :]))
                    print("LJ epsilon:",  np.amax(grads[:, 1, :, :]), np.amin(grads[:, 1, :, :]))
                else:
                    assert 0
            if np.any(np.isnan(dxdp)):
                assert 0


        context.step()

if __name__ == "__main__":


    smiles = "C1CCCCC1"

    parser = argparse.ArgumentParser(description='Stability testing.')
    parser.add_argument('--smiles', dest='smiles', help='what temperature we should run at')

    args = parser.parse_args()
    test_mol(args.smiles)


