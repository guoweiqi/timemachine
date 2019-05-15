import rdkit
from rdkit import Chem
import jax.numpy as np

from openforcefield.utils import toolkits

def match_bonds(mol, triples):
    """

    """
    bond_idxs = []
    param_idxs = []

    for smirks, k_idx, length_idx in triples:
        bond_idxs.append([bond.src, bond.dst])
        param_idxs.append([k_idx, length_idx])

    return bond_idxs, param_idxs


def parameterize(global_params, mol, forcefield):
    nrgs = []
    pattern = "[#6X4:1]-[#6X4:2]"
    mol = Chem.MolFromSmiles("Cc1ccccc1")

    for force_group in forcefield:
        if force_group == "Bond":
            parse_triples(force_group)
            bi, pi = match_bonds(mol, triples)
            harmonic_bond(conf, global_params, None, bond_idxs, param_idxs)
        elif force_group == "Angles":
            parse_triples(force_group)
            match_angles(mol, triples)

    kb, b0 = global_parameters[kb_idx, b0_idx]


results = toolkits.RDKitToolkitWrapper._find_smarts_matches(mol, pattern)
print(results)