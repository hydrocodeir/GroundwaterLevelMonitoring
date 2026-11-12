import importlib.util
from pathlib import Path
import math
import pytest

spec=importlib.util.spec_from_file_location('water_quality',Path(__file__).resolve().parents[1]/'scripts/waterq_compute.py')
quality=importlib.util.module_from_spec(spec);spec.loader.exec_module(quality)


def test_depth_fractions_have_analytic_limits_and_keep_unknown_anchor_explicit():
    assert quality.fraction_below(1000,1000,1)==1
    assert quality.fraction_below(1001,1000,1)==0
    assert quality.fraction_below(1000,1000,4)==pytest.approx(.5)
    assert quality.fraction_below(1000,500,4)==pytest.approx(0)
    assert quality.fraction_below(1000,2000,4)==pytest.approx(1)
    assert quality.fraction_below(1000,1000,.25)==pytest.approx(.5)
    for args in ((0,1000,1),(1000,-1,1),(1000,1000,0)):
        with pytest.raises(ValueError):quality.fraction_below(*args)


def test_fao_sar_ec_boundary_and_strict_lower_threshold():
    assert quality.irrigation_lower_ec(2)==200
    assert quality.irrigation_lower_ec(4)==300
    assert quality.irrigation_lower_ec(8)==500
    assert quality.irrigation_lower_ec(15)==1300
    assert quality.irrigation_lower_ec(30)==2900
    assert quality.irrigation_lower_ec(41) is None
    assert quality.irrigation_lower_ec(None) is None
    # At the severe-infiltration boundary, the water is not below the boundary.
    assert quality.fraction_below(200,math.nextafter(200,-math.inf),1)==0


def test_idw_preserves_a_known_constant_and_regression_uses_training_inputs_only():
    import numpy as np
    xy=np.array([[0,0],[1000,0],[1000,1000],[0,1000]])
    target=np.array([[400,600],[500,500]])
    assert quality.idw_predict(xy,np.full(4,7.),target)==pytest.approx([7,7])
    x=np.column_stack([xy,np.full(4,np.nan)])
    tx=np.column_stack([target,np.full(2,999999)])
    assert quality.regression_residual(xy,np.full(4,7.),target,x,tx)==pytest.approx([7,7])
