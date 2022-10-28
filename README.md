[![tests](https://github.com/LuisScoccola/persistable/actions/workflows/run_tests.yaml/badge.svg)](https://github.com/LuisScoccola/persistable/actions/workflows/run_tests.yaml)
[![coverage](https://codecov.io/gh/LuisScoccola/persistable/branch/main/graph/badge.svg)](https://codecov.io/gh/LuisScoccola/persistable)
[![docs](https://readthedocs.org/projects/persistable/badge/?version=latest)](https://persistable.readthedocs.io/)
[![license](https://img.shields.io/github/license/LuisScoccola/persistable)](https://github.com/LuisScoccola/persistable/blob/main/LICENSE)

# Persistable: persistent and stable clustering

Persistable is a density-based clustering algorithm intended for exploratory data analysis.
What distinguishes Persistable from other clustering algorithms is its visualization capabilities.
Persistable's interactive mode lets you visualize multi-scale and multi-density cluster structure present in the data.
This is used to guide the choice of parameters that lead to the final clustering.

Keep in mind that this is a beta version and the user interface may change with the stable release.


## Documentation

You can find the documentation at [persistable.readthedocs.io](https://persistable.readthedocs.io/).


## Usage

Here is a brief outline of the main functionality; see the [documentation](https://persistable.readthedocs.io/) for details, including the [API reference](https://persistable.readthedocs.io/en/latest/api.html).

### Basic usage

```python
import persistable
from sklearn.datasets import make_blobs

X = make_blobs(2000, random_state=1)[0]
p = persistable.Persistable(X)
clustering_labels = p.quick_cluster()
```


### Interactive mode 

For now, Persistable's interactive mode is supported through Jupyter notebooks.
In order to run Persistable's interactive mode from a Jupyter notebook, run the following in a Jupyter cell:

```python
import persistable
from sklearn.datasets import make_blobs

X = make_blobs(2000, centers=4, random_state=1)[0]
# using n_neighbors="all" will compute better defaults for visualization,
# but you might want to omit this for large datasets
p = persistable.Persistable(X, n_neighbors="all")
pi = persistable.PersistableInteractive(p)
pi.start_UI()
```

Now go to `localhost:8050` in your web browser to access the graphical user interface:

![Alt text](docs/pictures/GUI.png?raw=true)

After choosing your parameters using the user interface, you can get your clustering in another Jupyter cell by running:

```python
cluster_labels = pi.cluster()
```

**Note:** You may use `pi.start_UI(inline=True)` to have the graphical user interface display directly in the Jupyter notebook!


## Installing

Make sure you are using Python 3.
Installation through PyPI is coming soon.

```bash
pip install git+https://github.com/LuisScoccola/persistable.git
```


## Running the tests

You can run the tests by running the following commands from the root directory of a clone of this repository.
Note that, for now, *we are not testing the GUI*.
If a test fails, please [report a bug](https://github.com/LuisScoccola/persistable/issues).

```bash
pip install -r requirements.txt
python -m setup build_ext --inplace
pytest .
```


## Details about theory and implementation

Persistable is based on multi-parameter persistence [[4]](#4), a method from topological data analysis.
The theory behind Persistable is developed in [[1]](#1), while this implementation uses the high performance algorithms for density-based clustering developed in [[2]](#2) and implemented in [[3]](#3).
Persistable's interactive mode is inspired by RIVET [[5]](#5) and is implemented in [Dash](https://dash.plotly.com/).


## Contributing

To contribute, you can fork the project, make your changes, and submit a pull request.
You may want to contact [Luis Scoccola](https://luisscoccola.github.io/) first, to make sure your work does not overlap with ongoing work.
The next steps in our to-do list are:
- Tests for GUI.
- A tutorial with more examples.
- Improving the GUI's responsiveness and workflow.
- Computing and displaying further algebraic invariants of multi-parameter hierarchical clusterings.
- Improving efficiency of current algorithms.


## Authors

[Luis Scoccola](https://luisscoccola.github.io/) and [Alexander Rolle](https://alexanderrolle.github.io/).


## References

<a id="1">[1]</a> 
*Stable and consistent density-based clustering*. A. Rolle and L. Scoccola. [arXiv:2005.09048](https://arxiv.org/abs/2005.09048)

<a id="2">[2]</a> 
*Accelerated Hierarchical Density Based Clustering*. L. McInnes, J. Healy. 2017 IEEE International Conference on Data Mining Workshops (ICDMW), IEEE, pp 33-42. 2017

<a id="3">[3]</a> 
*hdbscan: Hierarchical density based clustering*. L. McInnes, J. Healy, S. Astels. Journal of Open Source Software, The Open Journal, volume 2, number 11. 2017

<a id="4">[4]</a> 
*An Introduction to Multiparameter Persistence*. M. B. Botnan, M. Lesnick. Proceedings of the 2020 International Conference on Representations of Algebras. 2022

<a id="5">[5]</a> 
*RIVET*. The RIVET Developers. [[Git]](https://github.com/rivetTDA/rivet) [[docs]](https://rivet.readthedocs.io/en/latest/index.html)

<!---
<a id="4">[4]</a> 
*Density-based clustering based on hierarchical density estimates*. R. J. G. B. Campello, D. Moulavi, and J. Sander. Advances in Knowledge Discovery and Data Mining, volume 7819 of Lecture Notes in Computer Science, pp. 160-172. Springer, 2013.
-->


## License

The software is published under the 3-clause BSD license.
