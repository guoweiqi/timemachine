import jax.numpy as np

from timemachine.jax_functionals import Energy
from timemachine.constants import ONE_4PI_EPS0
from timemachine.jax_functionals.jax_utils import delta_r, distance

class LeonnardJones(Energy):

    def __init__(self, param_idxs, scale_matrix, cutoff=None):
        """
        Implements a non-periodic LJ612 potential using the Lorentz−Berthelot combining
        rules, where sig_ij = (sig_i + sig_j)/2 and eps_ij = sqrt(eps_i * eps_j).

        Parameters
        ----------
        param_idxs: (N,2)
            each tuple (sig, eps) is used as part of the combining rules

        scale_matrix: (N, N)
            scale mask denoting how we should scale interaction e[i,j].
            The elements should be between [0, 1]. If e[i,j] is 1 then the interaction
            is fully included, 0 implies it is discarded.

        cutoff: float
            Whether or not we apply cutoffs to the system. Any interactions
            greater than cutoff is fully discarded.

        """
        self.param_idxs = param_idxs
        self.scale_matrix = scale_matrix
        self.cutoff = cutoff
        super().__init__()


    def energy(self, conf, params, box=None):
        """
        
        """
        sig = params[self.param_idxs[:, 0]]
        eps = params[self.param_idxs[:, 1]]

        sig_i = np.expand_dims(sig, 0)
        sig_j = np.expand_dims(sig, 1)
        sig_ij = (sig_i + sig_j)/2
        sig_ij_raw = sig_ij

        eps_i = np.expand_dims(eps, 0)
        eps_j = np.expand_dims(eps, 1)
        eps_ij = self.scale_matrix * np.sqrt(eps_i * eps_j)

        eps_ij_raw = eps_ij

        ri = np.expand_dims(conf, 0)
        rj = np.expand_dims(conf, 1)

        dij = distance(ri, rj, box)

        if self.cutoff is not None:
            eps_ij = np.where(dij < self.cutoff, eps_ij, np.zeros_like(eps_ij))

        keep_mask = self.scale_matrix > 0

        # (ytz): this avoids a nan in the gradient in both jax and tensorflow
        sig_ij = np.where(keep_mask, sig_ij, np.zeros_like(sig_ij))
        eps_ij = np.where(keep_mask, eps_ij, np.zeros_like(eps_ij))

        sig2 = sig_ij/dij
        sig2 *= sig2
        sig6 = sig2*sig2*sig2

        energy = 4*eps_ij*(sig6-1.0)*sig6
        energy = np.where(keep_mask, energy, np.zeros_like(energy))

        # divide by two to deal with symmetry
        return np.sum(energy, axis=-1)/2

# class Electrostatic(Energy):

#     def __init__(self, params, param_idxs, scale_matrix, cutoff=None, crf=1.0, kmax=10):
#         """
#         Implements electrostatic potential based on coloumb's law.

#         Parameters
#         ----------
#         params: tf.Tensor or numpy array
#             values used to look for param_idxs

#         param_idxs: (N,) tf.Tensor
#             indices into params for each atom corresponding to the charge

#         scale_matrix: (N, N) tf.Tensor
#             how much we scale each interaction by. Note that we follow OpenMM's convention,
#             if the scale_matrix[i,j] is exactly 1.0 and the cutoff is not None, then we apply
#             the crf correction. The scale matrices should be set to zero for 1-2 and 1-3 ixns.

#         cutoff: None or float > 0
#             whether or not we use cutoffs.

#         crf: float
#             how much we adjust the 1/dij in the event that we use cutoff and
#             the scale_matrix[i, j] == 1.0 

#         """

#         if cutoff is not None and cutoff <= 0.0:
#             raise ValueError("cutoff cannot be <= 0.0, did you mean None?")

#         self.params = params
#         self.param_idxs = param_idxs # length N
#         self.num_atoms = len(self.param_idxs)
#         self.charges = tf.gather(self.params, self.param_idxs)
#         self.charges = tf.reshape(self.charges, shape=(1, -1))
#         self.scale_matrix = scale_matrix
#         self.alphaEwald = 1.0
#         self.cutoff = cutoff
#         self.kmax = kmax
#         self.crf = crf

#     def energy(self, conf, box=None):
#         direct_nrg, exclusion_nrg = self.direct_and_exclusion_energy(conf, box)
#         if box is None:
#             return direct_nrg
#         else:
#             return self.reciprocal_energy(conf, box) + direct_nrg - exclusion_nrg - self.self_energy(conf)

#     def self_energy(self, conf):
#         return tf.reduce_sum(ONE_4PI_EPS0 * tf.pow(self.charges, 2) * self.alphaEwald/np.sqrt(np.pi))

#     def direct_and_exclusion_energy(self, conf, box):
#         charges = tf.gather(self.params, self.param_idxs)
#         qi = tf.expand_dims(charges, 0)
#         qj = tf.expand_dims(charges, 1)
#         qij = self.scale_matrix * tf.multiply(qi, qj)

#         ri = tf.expand_dims(conf, 0)
#         rj = tf.expand_dims(conf, 1)

#         if box is not None:
#             rij = ri - rj
#             base = tf.floor(rij/box + 0.5)*box # (ytz): can we differentiate through this?
#             dxdydz = tf.pow(rij-base, 2)
#             d2ij = tf.reduce_sum(dxdydz, axis=-1)
#         else:
#             d2ij = tf.reduce_sum(tf.pow(ri-rj, 2), axis=-1)

#         ones_mask = tf.ones(shape=[self.num_atoms, self.num_atoms], dtype=tf.int32)
#         on_diag_mask = tf.matrix_band_part(ones_mask, 0, 0)

#         # mask = d2ij != 0.0 doesn't work because gradients propagate through the first arg
#         d2ij_where = tf.where(tf.cast(ones_mask - on_diag_mask, dtype=tf.bool), d2ij, tf.zeros_like(d2ij))
#         dij_inverse = 1/tf.sqrt(d2ij_where)

#         if self.cutoff is not None:
#             # apply only to fully non-excepted terms
#             dij_inverse = tf.where(self.scale_matrix == 1.0, dij_inverse - self.crf, dij_inverse)
#             qij = tf.where(d2ij < self.cutoff*self.cutoff, qij, tf.zeros_like(qij))

#         direct_mask = self.scale_matrix > 0
#         qij_direct_mask = tf.boolean_mask(qij, direct_mask)
#         dij_inverse_mask =  tf.boolean_mask(dij_inverse, direct_mask)
#         eij_direct = qij_direct_mask * dij_inverse_mask

#         return ONE_4PI_EPS0*tf.reduce_sum(eij_direct, axis=-1)/2, None

#         # if box is not None:
#         #     # We adjust direct by the erfc, and adjust the reciprocal space's
#         #     # exclusionary contribution by the direction space weighted by erf
#         #     eij_direct *= tf.erfc(self.alphaEwald*r_direct)
#         #     # exclusions to subtract from reciprocal space
#         #     qij_exclusion_mask = tf.boolean_mask(qij, self.exclusion_mask)
#         #     d2ij_exclusion_mask = tf.boolean_mask(d2ij, self.exclusion_mask)
#         #     r_exclusion = tf.sqrt(d2ij_exclusion_mask)
#         #     eij_exclusion = qij_exclusion_mask/r_exclusion
#         #     eij_exclusion *= tf.erf(self.alphaEwald*r_exclusion)

#         #     # extra factor of 2 is to deal with the fact that we compute the full matrix as opposed to the upper right
#         #     return ONE_4PI_EPS0*tf.reduce_sum(eij_direct, axis=-1)/2, ONE_4PI_EPS0*tf.reduce_sum(eij_exclusion, axis=-1)
#         # else:
#         #     return ONE_4PI_EPS0*tf.reduce_sum(eij_direct, axis=-1)/2, None

#     def reciprocal_energy(self, conf, box):
#         assert box is not None

#         recipBoxSize = (2*np.pi)/box

#         mg = []
#         lowry = 0
#         lowrz = 1

#         numRx, numRy, numRz = self.kmax, self.kmax, self.kmax

#         for rx in range(numRx):
#             for ry in range(lowry, numRy):
#                 for rz in range(lowrz, numRz):
#                     mg.append((rx, ry, rz))
#                     lowrz = 1 - numRz
#                 lowry = 1 - numRy

#         # lattice vectors
#         ki = tf.expand_dims(recipBoxSize, axis=0) * mg # [nk, 3]
#         ri = tf.expand_dims(conf, axis=0) # [1, N, 3]
#         rik = tf.reduce_sum(tf.multiply(ri, tf.expand_dims(ki, axis=1)), axis=-1) # [nk, N]
#         real = tf.cos(rik)
#         imag = tf.sin(rik)
#         eikr = tf.complex(real, imag) # [nk, N]
#         qi = tf.complex(self.charges, np.float64(0.0))
#         Sk = tf.reduce_sum(qi*eikr, axis=-1)  # [nk]
#         n2Sk = tf.pow(tf.abs(Sk), 2)
#         k2 = tf.reduce_sum(tf.multiply(ki, ki), axis=-1) # [nk]
#         factorEwald = -1/(4*self.alphaEwald*self.alphaEwald)
#         ak = tf.exp(k2*factorEwald)/k2 # [nk]
#         nrg = tf.reduce_sum(ak * n2Sk)
#         recipCoeff = (ONE_4PI_EPS0*4*np.pi)/(box[0]*box[1]*box[2])

#         return recipCoeff * nrg
