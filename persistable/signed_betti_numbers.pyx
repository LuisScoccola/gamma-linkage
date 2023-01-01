# cython: boundscheck=False
# cython: nonecheck=False
# cython: wraparound=False
# cython: initializedcheck=False

import numpy as np
import itertools


cpdef signed_betti(hilbert_function):
    # number of dimensions
    n = len(hilbert_function.shape)
    # pad with zeros at the end so np.roll does not roll over
    hf_padded = np.pad(hilbert_function,[[0,1]]*n)
    # all relevant shifts (e.g., if n=2, (0,0), (0,1), (1,0), (1,1))
    shifts = np.array(list(itertools.product([0,1],repeat=n)), dtype=long)
    bn = np.zeros(hf_padded.shape, dtype=long)
    for shift in shifts:
        bn += ((-1)**np.sum(shift)) * np.roll(hf_padded,shift,axis=range(n))
    # remove the padding
    slices = np.ix_( *[range(0,hilbert_function.shape[i]) for i in range(n)] )
    return bn[slices]

cpdef rank_decomposition_2d_rectangles(long[:,:,:,:] rank_invariant):
    return np.flip(signed_betti(np.flip(rank_invariant,(2,3))),(2,3))

cpdef rank_decomposition_2d_rectangles_to_hooks(long[:,:,:,:] rdr):
    cdef long[:,:,:,:] rdr_view = rdr
    rdh = np.zeros_like(rdr, dtype=long)
    cdef long[:,:,:,:] rdh_view = rdh
    for i in range(rdr.shape[0]):
        for j in range(rdr.shape[1]):
            for i_ in range(i, rdr.shape[2]):
                for j_ in range(j, rdr.shape[3]):
                    rdh_view[i,j,up_i,up_j] -= rdr_view[i,j,i_,j_]
                    rdh_view[i,j,up_i,j] += rdr_view[i,j,i_,j_]
                    rdh_view[i,j,i,up_j] += rdr_view[i,j,i_,j_]
    return rdh
