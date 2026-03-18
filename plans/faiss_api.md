# Faiss Api:

## Index

```python
class Index(object):
    r"""
     Abstract structure for an index, supports adding vectors and searching
    them.

    All vectors provided at add or search time are 32-bit float arrays,
    although the internal representation may vary.
    """
    def train(self, n, x):
        r"""
         Perform training on a representative set of vectors

        :type n: int
        :param n:      nb of training vectors
        :type x: float
        :param x:      training vectors, size n * d
        """
        return _swigfaiss.Index_train(self, n, x)

    def train_ex(self, n, x, numeric_type):
        return _swigfaiss.Index_train_ex(self, n, x, numeric_type)

    def add(self, n, x):
        r"""
         Add n vectors of dimension d to the index.

        Vectors are implicitly assigned labels ntotal .. ntotal + n - 1
        This function slices the input vectors in chunks smaller than
        blocksize_add and calls add_core.
        :type n: int
        :param n:      number of vectors
        :type x: float
        :param x:      input matrix, size n * d
        """
        return _swigfaiss.Index_add(self, n, x)

    def add_ex(self, n, x, numeric_type):
        return _swigfaiss.Index_add_ex(self, n, x, numeric_type)

    def add_with_ids(self, n, x, xids):
        r"""
         Same as add, but stores xids instead of sequential ids.

        The default implementation fails with an assertion, as it is
        not supported by all indexes.

        :type n: int
        :param n:         number of vectors
        :type x: float
        :param x:         input vectors, size n * d
        :type xids: int
        :param xids:      if non-null, ids to store for the vectors (size n)
        """
        return _swigfaiss.Index_add_with_ids(self, n, x, xids)

    def add_with_ids_ex(self, n, x, numeric_type, xids):
        return _swigfaiss.Index_add_with_ids_ex(self, n, x, numeric_type, xids)

    def search(self, n, x, k, distances, labels, params=None):
        r"""
         query n vectors of dimension d to the index.

        return at most k vectors. If there are not enough results for a
        query, the result array is padded with -1s.

        :type n: int
        :param n:           number of vectors
        :type x: float
        :param x:           input vectors to search, size n * d
        :type k: int
        :param k:           number of extracted vectors
        :type distances: float
        :param distances:   output pairwise distances, size n*k
        :type labels: int
        :param labels:      output labels of the NNs, size n*k
        """
        return _swigfaiss.Index_search(self, n, x, k, distances, labels, params)

    def search_ex(self, n, x, numeric_type, k, distances, labels, params=None):
        return _swigfaiss.Index_search_ex(self, n, x, numeric_type, k, distances, labels, params)

    def range_search(self, n, x, radius, result, params=None):
        r"""
         query n vectors of dimension d to the index.

        return all vectors with distance < radius. Note that many
        indexes do not implement the range_search (only the k-NN search
        is mandatory).

        :type n: int
        :param n:           number of vectors
        :type x: float
        :param x:           input vectors to search, size n * d
        :type radius: float
        :param radius:      search radius
        :type result: :py:class:`RangeSearchResult`
        :param result:      result table
        """
        return _swigfaiss.Index_range_search(self, n, x, radius, result, params)

    def assign(self, n, x, labels, k=1):
        r"""
         return the indexes of the k vectors closest to the query x.

        This function is identical as search but only return labels of
        neighbors.
        :type n: int
        :param n:           number of vectors
        :type x: float
        :param x:           input vectors to search, size n * d
        :type labels: int
        :param labels:      output labels of the NNs, size n*k
        :type k: int, optional
        :param k:           number of nearest neighbours
        """
        return _swigfaiss.Index_assign(self, n, x, labels, k)

    def reset(self):
        r"""removes all elements from the database."""
        return _swigfaiss.Index_reset(self)

    def remove_ids(self, sel):
        r"""
         removes IDs from the index. Not supported by all
        indexes. Returns the number of elements removed.
        """
        return _swigfaiss.Index_remove_ids(self, sel)

    def reconstruct(self, key, recons):
        r"""
         Reconstruct a stored vector (or an approximation if lossy coding)

        this function may not be defined for some indexes
        :type key: int
        :param key:         id of the vector to reconstruct
        :type recons: float
        :param recons:      reconstructed vector (size d)
        """
        return _swigfaiss.Index_reconstruct(self, key, recons)

    def reconstruct_batch(self, n, keys, recons):
        r"""
         Reconstruct several stored vectors (or an approximation if lossy
        coding)

        this function may not be defined for some indexes
        :type n: int
        :param n:           number of vectors to reconstruct
        :type keys: int
        :param keys:        ids of the vectors to reconstruct (size n)
        :type recons: float
        :param recons:      reconstructed vector (size n * d)
        """
        return _swigfaiss.Index_reconstruct_batch(self, n, keys, recons)

    def reconstruct_n(self, i0, ni, recons):
        r"""
         Reconstruct vectors i0 to i0 + ni - 1

        this function may not be defined for some indexes
        :type i0: int
        :param i0:          index of the first vector in the sequence
        :type ni: int
        :param ni:          number of vectors in the sequence
        :type recons: float
        :param recons:      reconstructed vector (size ni * d)
        """
        return _swigfaiss.Index_reconstruct_n(self, i0, ni, recons)

    def search_and_reconstruct(self, n, x, k, distances, labels, recons, params=None):
        r"""
         Similar to search, but also reconstructs the stored vectors (or an
        approximation in the case of lossy coding) for the search results.

        If there are not enough results for a query, the resulting arrays
        is padded with -1s.

        :type n: int
        :param n:           number of vectors
        :type x: float
        :param x:           input vectors to search, size n * d
        :type k: int
        :param k:           number of extracted vectors
        :type distances: float
        :param distances:   output pairwise distances, size n*k
        :type labels: int
        :param labels:      output labels of the NNs, size n*k
        :type recons: float
        :param recons:      reconstructed vectors size (n, k, d)
        """
        return _swigfaiss.Index_search_and_reconstruct(self, n, x, k, distances, labels, recons, params)

    def search_subset(self, n, x, k_base, base_labels, k, distances, labels):
        r"""
         Similar to search, but operates on a potentially different subset
        of the dataset for each query.

        The default implementation fails with an assertion, as it is
        not supported by all indexes.

        :type n: int
        :param n:           number of vectors
        :type x: float
        :param x:           input vectors, size n * d
        :type k_base: int
        :param k_base:      number of vectors to search from
        :type base_labels: int
        :param base_labels: ids of the vectors to search from
        :type k: int
        :param k:           desired number of results per query
        :type distances: float
        :param distances:   output pairwise distances, size n*k
        :type labels: int
        :param labels:      output labels of the NNs, size n*k
        """
        return _swigfaiss.Index_search_subset(self, n, x, k_base, base_labels, k, distances, labels)

    def compute_residual(self, x, residual, key):
        r"""
         Computes a residual vector after indexing encoding.

        The residual vector is the difference between a vector and the
        reconstruction that can be decoded from its representation in
        the index. The residual can be used for multiple-stage indexing
        methods, like IndexIVF's methods.

        :type x: float
        :param x:           input vector, size d
        :type residual: float
        :param residual:    output residual vector, size d
        :type key: int
        :param key:         encoded index, as returned by search and assign
        """
        return _swigfaiss.Index_compute_residual(self, x, residual, key)

    def compute_residual_n(self, n, xs, residuals, keys):
        r"""
         Computes a residual vector after indexing encoding (batch form).
        Equivalent to calling compute_residual for each vector.

        The residual vector is the difference between a vector and the
        reconstruction that can be decoded from its representation in
        the index. The residual can be used for multiple-stage indexing
        methods, like IndexIVF's methods.

        :type n: int
        :param n:           number of vectors
        :type xs: float
        :param xs:          input vectors, size (n x d)
        :type residuals: float
        :param residuals:   output residual vectors, size (n x d)
        :type keys: int
        :param keys:        encoded index, as returned by search and assign
        """
        return _swigfaiss.Index_compute_residual_n(self, n, xs, residuals, keys)
	...
```