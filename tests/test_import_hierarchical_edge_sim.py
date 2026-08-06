import hierarchical_edge_sim
import hierarchical_edge_sim.env


def test_import_package():
    assert hierarchical_edge_sim.__version__ == "0.1.0"


def test_import_env_subpackage():
    assert hierarchical_edge_sim.env.__doc__ is not None
