import os
import unittest
import numpy as np

from simtk.openmm import app
from simtk import openmm as mm
from simtk import unit

from timemachine.lib import custom_ops
from timemachine.integrator import langevin_coefficients


def value(quantity):
    return quantity.value_in_unit_system(unit.md_unit_system)


class TestOverFit(unittest.TestCase):


    def test_overfit_host_acd(self):
        potentials, coords, (params, param_groups), masses = self.deserialize_system('examples/host_acd.xml')

        num_atoms = coords.shape[0]

        dt = 0.001
        ca, cb, cc = langevin_coefficients(
            temperature=100.0,
            dt=dt,
            friction=75,
            masses=masses
        )

        # minimization coefficients
        m_dt, m_ca, m_cb, m_cc = dt, 0.5, cb, np.zeros_like(masses)

        friction = 1.0

        print(m_dt, m_ca, m_cb, m_cc)

        # assert 0
        opt = custom_ops.LangevinOptimizer_f64(
            m_dt,
            m_ca,
            m_cb,
            m_cc
        )

        # test getting charges
        dp_idxs = np.argwhere(param_groups == 7).reshape(-1)

        ctxt = custom_ops.Context_f64(
            potentials,
            opt,
            params,
            coords, # x0
            np.zeros_like(coords), # v0
            # np.arange(len(params))
            dp_idxs
        )

        # minimize the system
        for i in range(10000):
            ctxt.step()
            if i % 100 == 0:
                print(i, ctxt.get_E())

        print(ctxt.get_dx_dp())

        opt.set_dt(dt)
        opt.set_coeff_a(ca)
        opt.set_coeff_b(cb)
        opt.set_coeff_c(cc)

        for i in range(10000):
            ctxt.step()
            if i % 100 == 0:
                print(i, ctxt.get_E())
            
        print(ctxt.get_dx_dp())


    def deserialize_system(self, filepath):
        """
        Deserialize an OpenMM XML file

        Parameters
        ----------
        filepath: str
            Location to an existing xml file to be deserialized

        """

        filename, file_extension = os.path.splitext(filepath)
        sys_xml = open(filepath, 'r').read()
        system = mm.XmlSerializer.deserialize(sys_xml)
        coords = np.loadtxt(filename + '.xyz').astype(np.float64)
        coords = coords/10

        global_params = []
        global_param_groups = []
        test_potentials = []

        def insert_parameters(obj, group):
            """
            Attempts to insert a value v and return the index it belongs to
            """
            p_idx = len(global_params)
            global_params.append(obj)
            global_param_groups.append(group)
            return p_idx

        masses = []

        for p in range(system.getNumParticles()):
            masses.append(value(system.getParticleMass(p)))

        for force in system.getForces():
            if isinstance(force, mm.HarmonicBondForce):
                bond_idxs = []
                param_idxs = []

                for b_idx in range(force.getNumBonds()):
                    src_idx, dst_idx, length, k = force.getBondParameters(b_idx)
                    length = value(length)
                    k = value(k)

                    k_idx = insert_parameters(k, 0)
                    b_idx = insert_parameters(length, 1)

                    param_idxs.append([k_idx, b_idx])
                    bond_idxs.append([src_idx, dst_idx])

                bond_idxs = np.array(bond_idxs, dtype=np.int32)
                param_idxs = np.array(param_idxs, dtype=np.int32)

                test_hb = custom_ops.HarmonicBond_f64(
                    bond_idxs,
                    param_idxs
                )

                test_potentials.append(test_hb)

            if isinstance(force, mm.HarmonicAngleForce):
                angle_idxs = []
                param_idxs = []

                for a_idx in range(force.getNumAngles()):
                    src_idx, mid_idx, dst_idx, angle, k = force.getAngleParameters(a_idx)
                    angle = value(angle)
                    k = value(k)

                    k_idx = insert_parameters(k, 2)
                    a_idx = insert_parameters(angle, 3)

                    param_idxs.append([k_idx, a_idx])
                    angle_idxs.append([src_idx, mid_idx, dst_idx])

                angle_idxs = np.array(angle_idxs, dtype=np.int32)
                param_idxs = np.array(param_idxs, dtype=np.int32)

                test_ha = custom_ops.HarmonicAngle_f64(
                    angle_idxs,
                    param_idxs
                )

                test_potentials.append(test_ha)

            if isinstance(force, mm.PeriodicTorsionForce):
                torsion_idxs = []
                param_idxs = []

                for t_idx in range(force.getNumTorsions()):
                    a_idx, b_idx, c_idx, d_idx, period, phase, k = force.getTorsionParameters(t_idx)

                    # period is unitless
                    phase = value(phase)
                    k = value(k)

                    k_idx = insert_parameters(k, 4)
                    phase_idx = insert_parameters(phase, 5)
                    period_idx = insert_parameters(period, 6)

                    param_idxs.append([k_idx, phase_idx, period_idx])
                    torsion_idxs.append([a_idx, b_idx, c_idx, d_idx])

                torsion_idxs = np.array(torsion_idxs, dtype=np.int32)
                param_idxs = np.array(param_idxs, dtype=np.int32)

                test_ha = custom_ops.PeriodicTorsion_f64(
                    torsion_idxs,
                    param_idxs
                )

                test_potentials.append(test_ha)

            if isinstance(force, mm.NonbondedForce):

                num_atoms = force.getNumParticles()
                scale_matrix = np.ones((num_atoms, num_atoms)) - np.eye(num_atoms)

                charge_param_idxs = []
                lj_param_idxs = []

                for a_idx in range(num_atoms):
                    charge, sig, eps = force.getParticleParameters(a_idx)

                    charge = value(charge)
                    sig = value(sig)
                    eps = value(eps)
                    if sig == 0 or eps == 0:
                        print("WARNING: invalid sig eps detected", sig, eps, "adjusting to 0.1 and 0.1")
                        assert eps == 0.0
                        sig = 0.1
                        eps = 0.1


                    charge_idx = insert_parameters(charge, 7)
                    sig_idx = insert_parameters(sig, 8)
                    eps_idx = insert_parameters(eps, 9)

                    charge_param_idxs.append(charge_idx)
                    lj_param_idxs.append([sig_idx, eps_idx])

                for a_idx in range(force.getNumExceptions()):

                    src, dst, _, _, _ = force.getExceptionParameters(a_idx)
                    scale_matrix[src][dst] = 0
                    scale_matrix[dst][src] = 0

                charge_param_idxs = np.array(charge_param_idxs, dtype=np.int32)
                lj_param_idxs = np.array(lj_param_idxs, dtype=np.int32)

                test_lj = custom_ops.LennardJones_f64(
                    scale_matrix,
                    lj_param_idxs
                )

                test_potentials.append(test_lj)

                test_es = custom_ops.Electrostatics_f64(
                    scale_matrix,
                    charge_param_idxs,
                )

                test_potentials.append(test_es)

        global_params = np.array(global_params)
        global_param_groups = np.array(global_param_groups)

        return test_potentials, coords, (global_params, global_param_groups), np.array(masses)
