# Authors: Luis Scoccola and Alexander Rolle
# License: 3-clause BSD

from ._vineyard import Vineyard
from .borrowed._hdbscan_boruvka import (
    KDTreeBoruvkaAlgorithm,
    BallTreeBoruvkaAlgorithm,
)
from .borrowed.prim_mst import mst_linkage_core_vector
from .borrowed.dense_mst import stepwise_dendrogram_with_core_distances
from .borrowed.dist_metrics import DistanceMetric
from .auxiliary import lazy_intersection
from .persistence_diagram_h0 import persistence_diagram_h0
from .signed_betti_numbers import (
    signed_betti,
    rank_decomposition_2d_rectangles,
    rank_decomposition_2d_rectangles_to_hooks,
)
import numpy as np
import warnings
from sklearn.neighbors import KDTree, BallTree
from scipy.cluster.hierarchy import DisjointSet
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import (
    minimum_spanning_tree as sparse_matrix_minimum_spanning_tree,
)
from scipy.stats import mode
from joblib import Parallel, delayed
from joblib.parallel import cpu_count


_TOL = 1e-08


def parallel_computation(function, inputs, n_jobs, debug=False, threading=False):
    if n_jobs == 1:
        return [function(inp) for inp in inputs]
    else:
        verbose = 11 if debug else 0
        n_jobs = min(cpu_count(), n_jobs)
        if threading:
            return Parallel(n_jobs=n_jobs, backend="threading", verbose=verbose)(
                delayed(function)(inp) for inp in inputs
            )
        else:
            return Parallel(n_jobs=n_jobs, verbose=verbose)(
                delayed(function)(inp) for inp in inputs
            )


class Persistable:
    """Does density-based clustering on finite metric spaces.

    Persistable has two main clustering methods: ``cluster()`` and ``quick_cluster()``.
    The methods are similar, the main difference being that ``quick_cluster()`` takes
    parameters that are sometimes easier to set. The parameters for ``cluster()``
    are usually set by using the graphical user interface implemented by the
    ``PersistableInteractive`` class.

    X: ndarray (n_samples, n_features)
        A numpy vector of shape (samples, features) or a distance matrix.

    metric: string, optional, default is "minkowski"
        A string determining which metric is used to compute distances
        between the points in X. It can be a metric in ``KDTree.valid_metrics``
        or ``BallTree.valid_metric`` (which can be found by
        ``from sklearn.neighbors import KDTree, BallTree``) or ``"precomputed"``
        if X is a distance matrix.

    n_neighbors: int or string, optional, default is "auto"
        Number of neighbors for each point in X used to initialize
        datastructures used for clustering. If set to ``"all"`` it will use
        the number of points in the dataset, if set to ``"auto"`` it will find
        a reasonable default.

    debug: bool, optional, default is False
        Whether to print debug messages.

    threading: bool, optional, default is False
        Whether to use python threads for parallel computation with ``joblib``.
        If false, the backend ``loky`` is used. In this case, using threads is
        significantly slower because of the GIL, but the backend ``loky`` does
        not work well in some systems.

    ``**kwargs``:
        Passed to ``KDTree`` or ``BallTree``.

    """

    def __init__(
        self,
        X,
        metric="minkowski",
        n_neighbors="auto",
        debug=False,
        threading=False,
        **kwargs
    ):
        self._debug = debug
        self._threading = threading
        # keep dataset
        self._data = X
        # if metric is minkowski but no p was passed, assume p = 2
        if metric == "minkowski" and "p" not in kwargs:
            kwargs["p"] = 2
        # if no measure was passed, assume normalized counting measure
        if "measure" not in kwargs:
            measure = np.full(X.shape[0], 1.0 / X.shape[0])
        elif "measure" in kwargs and kwargs["measure"] is None:
            measure = np.full(X.shape[0], 1.0 / X.shape[0])
            del kwargs["measure"]
        else:
            measure = kwargs["measure"]
            del kwargs["measure"]
        if "leaf_size" in kwargs:
            leaf_size = kwargs["leaf_size"]
        else:
            leaf_size = 40
        self._mpspace = _MetricProbabilitySpace(
            X, metric, measure, leaf_size, debug=debug, threading=threading, **kwargs
        )
        # if no n_neighbors for fitting mpspace was passed, compute a reasonable one
        if n_neighbors == "auto":
            if X.shape[0] < 100:
                self._n_neighbors = X.shape[0]
            else:
                self._n_neighbors = min(int(np.log10(X.shape[0])) * 100, X.shape[0])
        elif n_neighbors == "all":
            self._n_neighbors = X.shape[0]
        elif type(n_neighbors) == int and n_neighbors >= 1:
            self._n_neighbors = min(n_neighbors, X.shape[0])
        else:
            raise ValueError(
                "n_neighbors must be either auto, all, or a positive integer."
            )
        # keep max_k (normalized n_neighbors)
        self._maxk = self._n_neighbors / X.shape[0]
        # fit the mpspace
        self._mpspace.fit(self._n_neighbors)

    def quick_cluster(
        self,
        n_neighbors: int = 30,
        n_clusters_range=[3, 15],
        propagate_labels=False,
        n_iterations_propagate_labels=30,
        n_neighbors_propagate_labels=5,
    ):
        """Clusters the dataset with which the Persistable instance was initialized.

        This function will find the best number of clusterings in the range passed
        by the user, according to a certain measure of goodness of clustering
        based on prominence of modes of the underlying distribution.

        n_neighbors: int, optional, default is 30
            Number of neighbors used as a maximum density threshold
            when doing density-based clustering.

        n_clusters_range: (int, int), optional, default is [3, 15]
            A two-element list or tuple representing an integer
            range of possible numbers of clusters to consider when finding the
            optimum number of clusters.

        propagate_labels: bool, optional, default is False
            Boolean representing whether or not to extend the clustering to
            noise points by propagating labels.

        n_iterations_propagate_labels: int, optional, default is 30
            Maximum number of iterations of label propagation to perform. More iterations
            will cluster more noise points.

        n_neighbors_propagate_labels: int, optional, default is 5
            How many neighbors to use in the hill climbing procedure.

        returns:
            A numpy array of length the number of points in the dataset containing
            integers from -1 to the number of clusters minus 1, representing the
            labels of the final clustering. The label -1 represents noise points,
            i.e., points deemed not to belong to any cluster by the algorithm.

        """
        k = n_neighbors / self._mpspace._size
        default_percentile = 0.95
        s = self._mpspace.connection_radius(default_percentile) * 2

        hc = self._mpspace.lambda_linkage([0, k], [s, 0])
        pd = hc.persistence_diagram()
        if pd.shape[0] == 0:
            return np.full(self._mpspace._size, -1)

        def _prominences(bd):
            return np.sort(np.abs(bd[:, 0] - bd[:, 1]))[::-1]

        proms = _prominences(pd)
        if n_clusters_range[1] >= len(proms):
            return self.cluster(n_clusters_range[1], [0, k], [s, 0])
        logproms = np.log(proms)
        peaks = logproms[:-1] - logproms[1:]
        min_clust = n_clusters_range[0] - 1
        max_clust = n_clusters_range[1] - 1
        num_clust = np.argmax(peaks[min_clust:max_clust]) + min_clust + 1
        return self.cluster(
            num_clust,
            [0, k],
            [s, 0],
            propagate_labels=propagate_labels,
            n_iterations_propagate_labels=n_iterations_propagate_labels,
            n_neighbors_propagate_labels=n_neighbors_propagate_labels,
        )

    def cluster(
        self,
        n_clusters,
        start,
        end,
        propagate_labels=False,
        n_iterations_propagate_labels=30,
        n_neighbors_propagate_labels=5,
    ):
        """Clusters the dataset with which the Persistable instance was initialized.

        n_clusters: int
            Integer determining how many clusters the final clustering
            must have. Note that the final clustering can have fewer clusters
            if the selected parameters do not allow for so many clusters.

        start: (float, float)
            Two-element list, tuple, or numpy array representing a point on
            the positive plane determining the start of the segment in the
            two-parameter hierarchical clustering used to do persistence-based
            clustering.

        end: (float, float)
            Two-element list, tuple, or numpy array representing a point on
            the positive plane determining the end of the segment in the
            two-parameter hierarchical clustering used to do persistence-based
            clustering.

        propagate_labels: bool, optional, default is False
            Boolean representing whether or not to extend the clustering to
            noise points by propagating labels.

        n_iterations_propagate_labels: int, optional, default is 30
            Maximum number of iterations of label propagation to perform. More iterations
            will cluster more noise points.

        n_neighbors_propagate_labels: int, optional, default is 5
            How many neighbors to use in the hill climbing procedure.

        returns:
            A numpy array of length the number of points in the dataset containing
            integers from -1 to the number of clusters minus 1, representing the
            labels of the final clustering. The label -1 represents noise points,
            i.e., points deemed not to belong to any cluster by the algorithm.

        """

        start, end = np.array(start), np.array(end)
        if start.shape != (2,) or end.shape != (2,):
            raise ValueError("start and end must both be points on the plane.")
        if n_clusters < 1:
            raise ValueError("n_clusters must be greater than 0.")
        hc = self._mpspace.lambda_linkage(start, end)
        bd = hc.persistence_diagram()
        pers = np.abs(bd[:, 0] - bd[:, 1])
        # TODO: use sort from largest to smallest and make the logic below simpler
        spers = np.sort(pers)
        if n_clusters >= bd.shape[0]:
            if n_clusters > bd.shape[0]:
                warnings.warn(
                    "n_clusters is larger than the number of gaps, using n_clusters = number of gaps."
                )
            threshold = spers[0] / 2
        else:
            if np.abs(spers[-n_clusters] - spers[-(n_clusters + 1)]) < _TOL:
                warnings.warn(
                    "The gap selected is too small to produce a reliable clustering."
                )
            threshold = (spers[-n_clusters] + spers[-(n_clusters + 1)]) / 2
        cl = hc.persistence_based_flattening(threshold)
        if propagate_labels:
            cl = self._mpspace._propagate_labels(
                cl, n_iterations_propagate_labels, n_neighbors_propagate_labels
            )
        return cl

    def _find_end(self, fast=False):
        if fast:
            default_percentile = 0.95
            return self._mpspace.connection_radius(default_percentile) * 4, self._maxk
        else:
            return self._mpspace.find_end()

    def _compute_vineyard(self, start_end1, start_end2, n_parameters, n_jobs=4):
        start1, end1 = start_end1
        start2, end2 = start_end2
        if (
            start1[0] > end1[0]
            or start1[1] < end1[1]
            or start2[0] > end2[0]
            or start2[1] < end2[1]
        ):
            raise ValueError(
                "Parameters chosen for vineyard will result in non-monotonic lines!"
            )
        starts = list(
            zip(
                np.linspace(start1[0], start2[0], n_parameters),
                np.linspace(start1[1], start2[1], n_parameters),
            )
        )
        ends = list(
            zip(
                np.linspace(end1[0], end2[0], n_parameters),
                np.linspace(end1[1], end2[1], n_parameters),
            )
        )
        startends = list(zip(starts, ends))
        pds = self._mpspace.lambda_linkage_vineyard(startends, n_jobs=n_jobs)
        return Vineyard(startends, pds)

    def _compute_hilbert_function(
        self,
        min_s,
        max_s,
        max_k,
        min_k,
        granularity,
        n_jobs=4,
    ):
        if min_k >= max_k:
            raise ValueError("min_k must be smaller than max_k.")
        if min_s >= max_s:
            raise ValueError("min_s must be smaller than max_s.")
        if max_k > self._maxk:
            max_k = min(max_k, self._maxk)
            warnings.warn(
                "Not enough neighbors to compute chosen max density threshold, using "
                + str(max_k)
                + " instead. If needed, re-initialize the Persistable instance with a larger n_neighbors."
            )
        if min_k >= max_k:
            min_k = max_k / 2
            warnings.warn(
                "max density threshold too large, using " + str(min_k) + " instead."
            )

        ss = np.linspace(min_s, max_s, granularity)
        ks = np.linspace(min_k, max_k, granularity)[::-1]
        hf = self._mpspace.hilbert_function(ss, ks, n_jobs=n_jobs)
        return ss, ks, hf, signed_betti(hf)

    def _compute_rank_invariant(
        self,
        min_s,
        max_s,
        max_k,
        min_k,
        granularity,
        reduced=False,
        n_jobs=4,
    ):
        if min_k >= max_k:
            raise ValueError("min_k must be smaller than max_k.")
        if min_s >= max_s:
            raise ValueError("min_s must be smaller than max_s.")
        if max_k > self._maxk:
            max_k = min(max_k, self._maxk)
            warnings.warn(
                "Not enough neighbors to compute chosen max density threshold, using "
                + str(max_k)
                + " instead. If needed, re-initialize the Persistable instance with a larger n_neighbors."
            )
        if min_k >= max_k:
            min_k = max_k / 2
            warnings.warn(
                "max density threshold too large, using " + str(min_k) + " instead."
            )

        ss = np.linspace(min_s, max_s, granularity)
        ks = np.linspace(min_k, max_k, granularity)[::-1]
        ri = self._mpspace.rank_invariant(ss, ks, n_jobs=n_jobs, reduced=reduced)
        # need to cast explicitly to int64 for windows compatibility
        rdr = rank_decomposition_2d_rectangles(np.array(ri, dtype=np.int64))
        return ss, ks, ri, rdr, rank_decomposition_2d_rectangles_to_hooks(rdr)


class _MetricProbabilitySpace:
    """Implements a finite metric probability space that can compute its \
       kernel density estimates and lambda linkage hierarchical clusterings """

    _MAX_DIM_USE_BORUVKA = 60

    def __init__(
        self, X, metric, measure, leaf_size=40, debug=False, threading=False, **kwargs
    ):
        self._threading = threading
        self._debug = debug
        self._metric = metric
        self._kwargs = kwargs
        self._leaf_size = leaf_size
        self._size = X.shape[0]
        self._measure = measure
        self._dimension = X.shape[1]
        self._metric = metric
        if metric != "precomputed":
            self._points = X
        else:
            self._points = np.array(range(self._size))
        self._fitted_nn = False
        self._fitted_density_estimates = False
        self._nn_distance = None
        self._nn_indices = None
        self._kernel_estimate = None
        self._n_neighbors = None
        self._maxs = None
        if metric in KDTree.valid_metrics:
            self._tree = KDTree(X, metric=metric, leaf_size=leaf_size, **kwargs)
        elif metric in BallTree.valid_metrics:
            self._tree = BallTree(X, metric=metric, leaf_size=leaf_size, **kwargs)
        elif metric == "precomputed":
            self._dist_mat = np.array(X)
        else:
            raise ValueError("Metric given is not supported.")

    def fit(self, n_neighbors):
        self._fit_nn(n_neighbors)
        self._fit_density_estimates()
        self._maxk = self._n_neighbors / self._size

    def _fit_nn(self, n_neighbors):
        self._n_neighbors = n_neighbors
        if self._metric in BallTree.valid_metrics + KDTree.valid_metrics:
            k_neighbors = self._tree.query(
                self._points,
                self._n_neighbors,
                return_distance=True,
                sort_results=True,
                dualtree=True,
                breadth_first=True,
            )
            k_neighbors = (np.array(k_neighbors[1]), np.array(k_neighbors[0]))
            maxs_given_by_n_neighbors = np.min(k_neighbors[1][:, -1])
            self._maxs = maxs_given_by_n_neighbors
            neighbors = k_neighbors[0]
            _nn_distance = k_neighbors[1]
        else:
            self._n_neighbors = self._size
            self._maxs = 0
            neighbors = np.argsort(self._dist_mat)
            _nn_distance = self._dist_mat[
                np.arange(len(self._dist_mat)), neighbors.transpose()
            ].transpose()
        self._nn_indices = np.array(neighbors, dtype=np.int_)
        self._nn_distance = np.array(_nn_distance)
        self._fitted_nn = True

    def _fit_density_estimates(self):
        self._fitted_density_estimates = True
        self._kernel_estimate = np.cumsum(self._measure[self._nn_indices], axis=1)

    def _core_distance(self, point_index, s_intercept, k_intercept, max_k=None):
        max_k = k_intercept if max_k is None else max_k
        if s_intercept != np.inf:
            i_indices_and_finished_at_last_index = []
            mu = s_intercept / k_intercept
            k_to_s = lambda y: s_intercept - mu * y
            max_k_larger_last_kernel_estimate = []
            for p in point_index:
                i_indices_and_finished_at_last_index.append(
                    lazy_intersection(
                        self._kernel_estimate[p],
                        self._nn_distance[p],
                        s_intercept,
                        k_intercept,
                    )
                )
                max_k_larger_last_kernel_estimate.append(
                    (self._kernel_estimate[p, -1] < max_k)
                )
            max_k_larger_last_kernel_estimate = np.array(
                max_k_larger_last_kernel_estimate
            )
            i_indices_and_finished_at_last_index = np.array(
                i_indices_and_finished_at_last_index
            )
            i_indices = i_indices_and_finished_at_last_index[:, 0]
            finished_at_last_index = i_indices_and_finished_at_last_index[:, 1]
            # check if for any points we don't have enough neighbors to properly compute its core scale
            # for this, the lazy intersection must have finished at the last index and the max_k
            # of the line segment chosen must be larger than the max kernel estimate for the point
            if np.any(
                np.logical_and(
                    finished_at_last_index, max_k_larger_last_kernel_estimate
                )
            ):
                warnings.warn(
                    "Don't have enough neighbors to properly compute core scale, or point takes too long to appear."
                )
            op = lambda p, i: np.where(
                k_to_s(self._kernel_estimate[p, i - 1]) <= self._nn_distance[p, i],
                k_to_s(self._kernel_estimate[p, i - 1]),
                self._nn_distance[p, i],
            )
            return np.where(i_indices == 0, 0, op(point_index, i_indices))
        else:
            i_indices = []
            for p in point_index:
                idx = np.searchsorted(self._kernel_estimate[p], k_intercept, side="left")
                if idx == self._nn_distance[p].shape[0]:
                    idx -= 1
                i_indices.append(idx)
            i_indices = np.array(i_indices)
            # TODO: properly check and warn of not enough n_neighbors or
            # explicitly ensure that the following does not happen:
            #if self._n_neighbors < self._size:
            #    out_of_range = np.where(
            #        (
            #            i_indices
            #            >= np.apply_along_axis(len, -1, self._nn_indices[point_index])
            #        )
            #        & (
            #            np.apply_along_axis(len, -1, self._nn_indices[point_index])
            #            < self._size
            #        ),
            #        True,
            #        False,
            #    )
            #    if np.any(out_of_range):
            #        warnings.warn(
            #            "Don't have enough neighbors to properly compute core scale."
            #        )
            return self._nn_distance[(point_index, i_indices)]

    def find_end(self, tolerance=1e-4):
        def pers_diag(k):
            return self.lambda_linkage([0, k], [np.infty, k]).persistence_diagram()

        lower_bound = 0
        upper_bound = self._maxk

        i = 0
        while True:
            current_k = (lower_bound + upper_bound) / 2
            i += 1

            pd = pers_diag(current_k)
            pd = np.array(pd)
            # if len(pd[pd[:,1] == np.infty]) > 1:
            #    raise Exception("End not found! Try setting auto_find_end_hierachical_clustering to False.")
            if pd.shape[0] == 0:
                raise Exception(
                    "Empty persistence diagram found when trying to find end of metric measure space."
                )
            # persistence diagram has more than one class
            elif pd.shape[0] > 1:
                lower_bound, upper_bound = current_k, upper_bound
                if np.abs(current_k - self._maxk) < _TOL:
                    pd = pers_diag(lower_bound)
                    return [np.max(pd[pd[:, 1] != np.infty][:, 1]), current_k]
            # persistence diagram has exactly one class
            else:
                lower_bound, upper_bound = lower_bound, current_k

            if np.abs(lower_bound - upper_bound) < tolerance:
                pd = pers_diag(lower_bound)
                return [np.max(pd[pd[:, 1] != np.infty][:, 1]), current_k]

    # given a list of point indices and a radius, return the (unnormalized)
    # kernel density estimate at those points and at that radius
    def _density_estimate(self, point_index, radius, max_density=1):
        density_estimates = []
        out_of_range = False
        for p in point_index:
            if self._kernel_estimate[p, -1] < max_density:
                out_of_range = True
            neighbor_idx = np.searchsorted(self._nn_distance[p], radius, side="right")
            density_estimates.append(self._kernel_estimate[p, neighbor_idx - 1])
        if out_of_range:
            warnings.warn("Don't have enough neighbors to properly compute core scale.")
        return np.array(density_estimates)

    def _lambda_linkage_vertical(self, s_intercept, k_start, k_end):
        if k_end > k_start:
            raise ValueError("Parameters do not give a monotonic line.")

        indices = np.arange(self._size)
        k_births = self._density_estimate(indices, s_intercept, max_density=k_start)
        # must add 1 otherwise the edges (below) are treated as not there by mst routine
        k_births = k_start - np.maximum(k_end, np.minimum(k_start, k_births)) + 1

        # metric tree case
        if self._metric in KDTree.valid_metrics + BallTree.valid_metrics:
            s_neighbors = self._tree.query_radius(self._points, s_intercept)
        # dense distance matrix case
        else:
            s_neighbors = []
            for i in range(self._size):
                s_neighbors.append(np.argwhere(self._dist_mat[i] <= s_intercept)[:, 0])

        edges = []
        entries = []
        for i in range(self._size):
            for j in s_neighbors[i]:
                if j > i:
                    edges.append([i, j])
                    entries.append(max(k_births[i], k_births[j]))
        matrix_entries = np.array(entries)
        edges = np.array(edges, dtype=int)
        if len(edges) > 0:
            graph = csr_matrix(
                (matrix_entries, (edges[:, 0], edges[:, 1])), (self._size, self._size)
            )

            mst = sparse_matrix_minimum_spanning_tree(graph)
            Is, Js = mst.nonzero()
            # we now undo the adding 1
            vals = np.array(mst[Is, Js])[0] - 1
            sort_indices = np.argsort(vals)
            Is = Is[sort_indices]
            Js = Js[sort_indices]
            vals = vals[sort_indices]
            merges = np.zeros((vals.shape[0], 2), dtype=int)
            merges[:, 0] = Is
            merges[:, 1] = Js
            merges_heights = vals
        else:
            merges = np.array([], dtype=int)
            merges_heights = np.array([])
        hc_start = 0
        hc_end = k_start - k_end
        # we now undo the adding 1
        core_scales = k_births - 1

        return _HierarchicalClustering(
            core_scales, merges, merges_heights, hc_start, hc_end
        )

    def _lambda_linkage_skew(self, start, end):
        def _startend_to_intercepts(start, end):
            if end[0] == np.infty or start[1] == end[1]:
                k_intercept = start[1]
                s_intercept = np.infty
            else:
                slope = (end[1] - start[1]) / (end[0] - start[0])
                k_intercept = -start[0] * slope + start[1]
                s_intercept = -k_intercept / slope
            return s_intercept, k_intercept

        hc_start = start[0]
        hc_end = end[0]
        indices = np.arange(self._size)
        s_intercept, k_intercept = _startend_to_intercepts(start, end)
        max_k = start[1]
        core_distances = self._core_distance(indices, s_intercept, k_intercept, max_k)
        core_distances = np.minimum(hc_end, core_distances)
        core_distances = np.maximum(hc_start, core_distances)
        if self._metric in KDTree.valid_metrics:
            if self._dimension > self._MAX_DIM_USE_BORUVKA:
                X = self._points
                if not X.flags["C_CONTIGUOUS"]:
                    X = np.array(X, dtype=np.double, order="C")
                dist_metric = DistanceMetric.get_metric(self._metric, **self._kwargs)
                sl = mst_linkage_core_vector(X, core_distances, dist_metric)
            else:
                sl = KDTreeBoruvkaAlgorithm(
                    self._tree,
                    core_distances,
                    self._nn_indices,
                    leaf_size=self._leaf_size // 3,
                    metric=self._metric,
                    **self._kwargs
                ).spanning_tree()
        elif self._metric in BallTree.valid_metrics:
            if self._dimension > self._MAX_DIM_USE_BORUVKA:
                X = self._points
                if not X.flags["C_CONTIGUOUS"]:
                    X = np.array(X, dtype=np.double, order="C")
                dist_metric = DistanceMetric.get_metric(self._metric, **self._kwargs)
                sl = mst_linkage_core_vector(X, core_distances, dist_metric)
            else:
                sl = BallTreeBoruvkaAlgorithm(
                    self._tree,
                    core_distances,
                    self._nn_indices,
                    leaf_size=self._leaf_size // 3,
                    metric=self._metric,
                    **self._kwargs
                ).spanning_tree()
        else:
            sl = stepwise_dendrogram_with_core_distances(
                self._size, self._dist_mat, core_distances
            )
        merges = sl[:, 0:2].astype(int)
        # label(merges, self._size, merges.shape[0])
        merges_heights = np.minimum(hc_end, sl[:, 2])
        merges_heights = np.maximum(hc_start, sl[:, 2])
        return _HierarchicalClustering(
            core_distances, merges, merges_heights, hc_start, hc_end
        )

    def lambda_linkage(self, start, end):
        if start[0] > end[0] or start[1] < end[1]:
            raise ValueError("Parameters do not give a monotonic line.")

        if start[0] == end[0]:
            s_intercept = start[0]
            k_start = start[1]
            k_end = end[1]
            return self._lambda_linkage_vertical(s_intercept, k_start, k_end)
        else:
            return self._lambda_linkage_skew(start, end)

    def lambda_linkage_vineyard(self, startends, n_jobs, reduced=False, tol=_TOL):
        run_in_parallel = lambda startend: self.lambda_linkage(
            startend[0], startend[1]
        ).persistence_diagram(tol=tol, reduced=reduced)

        return parallel_computation(
            run_in_parallel,
            startends,
            n_jobs,
            debug=self._debug,
            threading=self._threading,
        )

    def rank_invariant(self, ss, ks, n_jobs, reduced=False):
        n_s = len(ss)
        n_k = len(ks)
        ks = np.array(ks)
        startends_horizontal = [[[ss[0], k], [ss[-1], k]] for k in ks]
        startends_vertical = [[[s, ks[0]], [s, ks[-1]]] for s in ss]
        startends = startends_horizontal + startends_vertical
        run_in_parallel = lambda startend: self.lambda_linkage(startend[0], startend[1])
        hcs = parallel_computation(
            run_in_parallel,
            startends,
            n_jobs,
            debug=self._debug,
            threading=self._threading,
        )
        hcs_horizontal = hcs[:n_k]
        for hc in hcs_horizontal:
            hc.snap_to_grid(ss)
        hcs_vertical = hcs[n_k:]
        for hc in hcs_vertical:
            hc.snap_to_grid(ks[0] - ks)

        def _splice_hcs(s_index, k_index):
            # the horizontal hierarchical clustering
            hor_hc = hcs_horizontal[k_index]
            # keep only things that happened before s_index
            hor_heights = hor_hc._heights.copy()
            hor_heights[hor_heights >= s_index] = s_index + len(ks) - k_index + 1
            hor_merges = hor_hc._merges[hor_hc._merges_heights < s_index]
            hor_merges_heights = hor_hc._merges_heights[
                hor_hc._merges_heights < s_index
            ]
            hor_end = s_index - 1
            hor_start = hor_hc._start

            # the vertical hierarchical clustering
            ver_hc = hcs_vertical[s_index]
            # push all things that happened before k_index there, and index starting from s_index
            ver_heights = s_index + np.maximum(k_index, ver_hc._heights) - k_index
            ver_merges_heights = (
                s_index + np.maximum(k_index, ver_hc._merges_heights) - k_index
            )
            # same merges in same order
            ver_merges = ver_hc._merges

            ver_start = s_index
            ver_end = s_index + ver_hc._end - k_index + 1

            heights = np.minimum(hor_heights, ver_heights)
            if len(hor_merges) == 0 and len(ver_merges) == 0:
                merges = np.array([], dtype=int)
            else:
                if len(hor_merges) == 0:
                    hor_merges.reshape([0, 2])
                if len(ver_merges) == 0:
                    ver_merges.reshape([0, 2])
                merges = np.concatenate((hor_merges, ver_merges))
            merges_heights = np.concatenate((hor_merges_heights, ver_merges_heights))
            start = hor_start
            end = ver_end

            return _HierarchicalClustering(heights, merges, merges_heights, start, end)

        def _pd_spliced_hc(s_index_k_index):
           s_index, k_index = s_index_k_index
           return _splice_hcs(s_index,k_index).persistence_diagram(reduced=reduced)

        indices = [[s_index,k_index] for s_index in range(n_s) for k_index in range(n_k) ]
        pds = parallel_computation(_pd_spliced_hc, indices, n_jobs, debug=self._debug, threading=self._threading)
        pds = [[indices[i][0],indices[i][1],pds[i]] for i in range(len(indices)) ]

        ri = np.zeros((n_s, n_k, n_s, n_k), dtype=int)

        for s_index, k_index, pd in pds:
            for bar in pd:
                b, d = bar
                b, d = int(b), int(d)
                # this if may be unnecessary
                if b <= s_index and d >= s_index:
                    for i in range(b,s_index+1):
                        for j in range(s_index,d):
                            ri[i, k_index, s_index, j-s_index+k_index] += 1
        return ri

    def hilbert_function(self, ss, ks, n_jobs):
        n_s = len(ss)
        n_k = len(ks)
        # go on one more step to compute the Hilbert function at the last point
        ss = list(ss)
        ss.append(ss[-1] + _TOL)
        startends = [[[ss[0], k], [ss[-1], k]] for k in ks]
        pds = self.lambda_linkage_vineyard(startends, n_jobs=n_jobs)
        hf = np.zeros((n_s, n_k), dtype=int)
        for i, pd in enumerate(pds):
            for bar in pd:
                b, d = bar
                start = np.searchsorted(ss[:-1], b)
                end = np.searchsorted(ss[:-1], d)
                hf[start:end, i] += 1
        return hf

    def connection_radius(self, percentiles=1):
        hc = self.lambda_linkage([0, 0], [np.infty, 0])
        return np.quantile(hc._merges_heights, percentiles)

    def _propagate_labels(self, labels, n_iterations, n_neighbors):
        old_labels = labels
        for _ in range(n_iterations):
            new_labels = []
            for x in range(self._size):
                if old_labels[x] == -1:
                    neighbors_labels = old_labels[self._nn_indices[x, :n_neighbors]]
                    neighbors_labels = neighbors_labels[neighbors_labels != -1]
                    if len(neighbors_labels) == 0:
                        new_labels.append(-1)
                    else:
                        new_labels.append(mode(neighbors_labels, keepdims=True)[0][0])
                else:
                    new_labels.append(old_labels[x])
            new_labels = np.array(new_labels)
            old_labels = new_labels
            if np.array_equal(new_labels, old_labels):
                break
        return new_labels


class _HierarchicalClustering:
    def __init__(self, heights, merges, merges_heights, start, end):
        # assumes heights and merges_heights are between start and end
        self._merges = np.array(merges, dtype=int)
        self._merges_heights = np.array(merges_heights, dtype=float)
        self._heights = np.array(heights, dtype=float)
        self._start = start
        self._end = end
        # persistence_diagram_h0 will fail if it receives an empty array
        if self._merges.shape[0] == 0:
            self._merges = np.array([[0, 0]], dtype=int)
            self._merges_heights = np.array([self._end], dtype=float)

    def snap_to_grid(self, grid):
        def _snap_array(grid, arr):
            res = np.zeros(arr.shape[0], dtype=int)
            # assumes grid and arr are ordered smallest to largest
            res[arr <= grid[0]] = 0
            for i in range(len(grid) - 1):
                res[(arr <= grid[i + 1]) & (arr > grid[i])] = i + 1
            res[arr > grid[-1]] = len(grid)
            return res

        self._merges_heights = _snap_array(grid, self._merges_heights)
        self._heights = _snap_array(grid, self._heights)
        self._start, self._end = _snap_array(grid, np.array([self._start, self._end]))

    def persistence_based_flattening(self, threshold):
        end = self._end
        heights = self._heights
        merges = self._merges
        merges_heights = self._merges_heights
        n_points = heights.shape[0]
        n_merges = merges.shape[0]
        # this orders the point by appearance
        appearances = np.argsort(heights)
        # contains the current clusters
        uf = DisjointSet()
        # contains the birth time of clusters that are alive
        clusters_birth = {}
        clusters_died = {}
        # contains the flat clusters
        clusters = []
        # height index
        hind = 0
        # merge index
        mind = 0
        current_appearence_height = heights[appearances[0]]
        current_merge_height = merges_heights[0]
        while True:
            # while there is no merge
            while (
                hind < n_points
                and heights[appearances[hind]] <= current_merge_height
                and heights[appearances[hind]] < end
            ):
                # add all points that are born as new clusters
                uf.add(appearances[hind])
                clusters_birth[appearances[hind]] = heights[appearances[hind]]
                hind += 1
                if hind == n_points:
                    current_appearence_height = end
                else:
                    current_appearence_height = heights[appearances[hind]]
            # while there is no cluster being born
            while (
                mind < n_merges
                and merges_heights[mind] < current_appearence_height
                and merges_heights[mind] < end
            ):
                xy = merges[mind]
                x, y = xy
                rx = uf.__getitem__(x)
                ry = uf.__getitem__(y)
                # if both clusters are alive
                if rx not in clusters_died and ry not in clusters_died:
                    bx = clusters_birth[rx]
                    by = clusters_birth[ry]
                    # if both have lived for more than the threshold, have them as flat clusters
                    if (
                        bx + threshold <= merges_heights[mind]
                        and by + threshold <= merges_heights[mind]
                    ):
                        clusters.append(list(uf.subset(x)))
                        clusters.append(list(uf.subset(y)))
                        uf.merge(x, y)
                        rxy = uf.__getitem__(x)
                        clusters_died[rxy] = True
                    # otherwise, merge them
                    else:
                        # then merge them
                        del clusters_birth[rx]
                        del clusters_birth[ry]
                        uf.merge(x, y)
                        rxy = uf.__getitem__(x)
                        clusters_birth[rxy] = min(bx, by)
                # if both clusters are already dead, just merge them into a dead cluster
                elif rx in clusters_died and ry in clusters_died:
                    uf.merge(x, y)
                    rxy = uf.__getitem__(x)
                    clusters_died[rxy] = True
                # if only one of them is dead
                else:
                    # we make it so that ry already died and rx just died
                    if rx in clusters_died:
                        x, y = y, x
                        rx, ry = ry, rx
                    # if x has lived for longer than the threshold, have it as a flat cluster
                    if clusters_birth[rx] + threshold <= merges_heights[mind]:
                        clusters.append(list(uf.subset(x)))
                    # then merge the clusters into a dead cluster
                    uf.merge(x, y)
                    rxy = uf.__getitem__(x)
                    clusters_died[rxy] = True
                mind += 1
                if mind == n_merges:
                    current_merge_height = end
                else:
                    current_merge_height = merges_heights[mind]
            if (hind == n_points or heights[appearances[hind]] >= end) and (
                mind == n_merges or merges_heights[mind] >= end
            ):
                break
        # go through all clusters that have been born but haven't been merged
        for x in range(n_points):
            if x in uf._indices:
                rx = uf.__getitem__(x)
                if rx not in clusters_died:
                    if clusters_birth[rx] + threshold <= end:
                        clusters.append(list(uf.subset(x)))
                    clusters_died[rx] = True
        current_cluster = 0
        res = np.full(n_points, -1)
        for cl in clusters:
            for x in cl:
                if x < n_points:
                    res[x] = current_cluster
            current_cluster += 1
        return res

    def persistence_diagram(self, reduced=False, tol=_TOL):
        # need to cast explicitly to int64 for windows compatibility
        pd = persistence_diagram_h0(
            self._end, self._heights, np.array(self._merges,dtype=np.int64), self._merges_heights
        )
        pd = np.array(pd)
        if pd.shape[0] == 0:
            return np.array([])
        pd = pd[np.abs(pd[:, 0] - pd[:, 1]) > tol]
        if reduced:
            to_delete = np.argmax(pd[:, 1] - pd[:, 0])
            return np.delete(pd, to_delete, axis=0)
        return pd
