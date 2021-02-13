#   Copyright 2020 The PyMC Developers
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

import aesara
import aesara.sparse as sparse
import aesara.tensor as aet
import numpy as np
import numpy.ma as ma
import numpy.testing as npt
import pandas as pd
import pytest
import scipy.sparse as sps

from aesara.tensor.var import TensorConstant, TensorVariable

import pymc3 as pm


class TestHelperFunc:
    @pytest.mark.parametrize("input_dtype", ["int32", "int64", "float32", "float64"])
    def test_pandas_to_array(self, input_dtype):
        """
        Ensure that pandas_to_array returns the dense array, masked array,
        graph variable, TensorVariable, or sparse matrix as appropriate.
        """
        # Create the various inputs to the function
        sparse_input = sps.csr_matrix(np.eye(3)).astype(input_dtype)
        dense_input = np.arange(9).reshape((3, 3)).astype(input_dtype)

        input_name = "input_variable"
        aesara_graph_input = aet.as_tensor(dense_input, name=input_name)
        pandas_input = pd.DataFrame(dense_input)

        # All the even numbers are replaced with NaN
        missing_numpy_input = np.array([[np.nan, 1, np.nan], [3, np.nan, 5], [np.nan, 7, np.nan]])
        missing_pandas_input = pd.DataFrame(missing_numpy_input)
        masked_array_input = ma.array(dense_input, mask=(np.mod(dense_input, 2) == 0))

        # Create a generator object. Apparently the generator object needs to
        # yield numpy arrays.
        square_generator = (np.array([i ** 2], dtype=int) for i in range(100))

        # Alias the function to be tested
        func = pm.model.pandas_to_array

        #####
        # Perform the various tests
        #####
        # Check function behavior with dense arrays and pandas dataframes
        # without missing values
        for input_value in [dense_input, pandas_input]:
            func_output = func(input_value)
            assert isinstance(func_output, np.ndarray)
            assert func_output.shape == input_value.shape
            npt.assert_allclose(func_output, dense_input)

        # Check function behavior with sparse matrix inputs
        sparse_output = func(sparse_input)
        assert sps.issparse(sparse_output)
        assert sparse_output.shape == sparse_input.shape
        npt.assert_allclose(sparse_output.toarray(), sparse_input.toarray())

        # Check function behavior when using masked array inputs and pandas
        # objects with missing data
        for input_value in [missing_numpy_input, masked_array_input, missing_pandas_input]:
            func_output = func(input_value)
            assert isinstance(func_output, ma.core.MaskedArray)
            assert func_output.shape == input_value.shape
            npt.assert_allclose(func_output, masked_array_input)

        # Check function behavior with Aesara graph variable
        aesara_output = func(aesara_graph_input)
        assert isinstance(aesara_output, aesara.graph.basic.Variable)
        npt.assert_allclose(aesara_output.eval(), aesara_graph_input.eval())
        intX = pm.aesaraf._conversion_map[aesara.config.floatX]
        if dense_input.dtype == intX or dense_input.dtype == aesara.config.floatX:
            assert aesara_output.owner is None  # func should not have added new nodes
            assert aesara_output.name == input_name
        else:
            assert aesara_output.owner is not None  # func should have casted
            assert aesara_output.owner.inputs[0].name == input_name

        if "float" in input_dtype:
            assert aesara_output.dtype == aesara.config.floatX
        else:
            assert aesara_output.dtype == intX

        # Check function behavior with generator data
        generator_output = func(square_generator)

        # Output is wrapped with `pm.floatX`, and this unwraps
        wrapped = generator_output.owner.inputs[0]
        # Make sure the returned object has .set_gen and .set_default methods
        assert hasattr(wrapped, "set_gen")
        assert hasattr(wrapped, "set_default")
        # Make sure the returned object is a Aesara TensorVariable
        assert isinstance(wrapped, TensorVariable)

    @pytest.mark.xfail(reason="`Observed` `Op` doesn't take `SparseConstant`s, yet")
    def test_make_obs_var(self):
        """
        Check returned values for `data` given known inputs to `as_tensor()`.

        Note that ndarrays should return a TensorConstant and sparse inputs
        should return a Sparse Aesara object.
        """
        # Create the various inputs to the function
        input_name = "testing_inputs"
        sparse_input = sps.csr_matrix(np.eye(3))
        dense_input = np.arange(9).reshape((3, 3))
        masked_array_input = ma.array(dense_input, mask=(np.mod(dense_input, 2) == 0))

        # Create a fake model and fake distribution to be used for the test
        fake_model = pm.Model()
        with fake_model:
            fake_distribution = pm.Normal.dist(mu=0, sigma=1)
            # Create the testval attribute simply for the sake of model testing
            fake_distribution.testval = None

        # Check function behavior using the various inputs
        dense_output = pm.model.make_obs_var(fake_distribution, dense_input, input_name, fake_model)
        sparse_output = pm.model.make_obs_var(
            fake_distribution, sparse_input, input_name, fake_model
        )
        masked_output = pm.model.make_obs_var(
            fake_distribution, masked_array_input, input_name, fake_model
        )

        # Ensure that the missing values are appropriately set to None
        for func_output in [dense_output, sparse_output]:
            assert func_output.missing_values is None

        # Ensure that the Aesara variable names are correctly set.
        # Note that the output for masked inputs do not have their names set
        # to the passed value.
        for func_output in [dense_output, sparse_output]:
            assert func_output.name == input_name

        # Ensure the that returned functions are all of the correct type
        assert isinstance(dense_output, TensorConstant)
        assert sparse.basic._is_sparse_variable(sparse_output)

        # Masked output is something weird. Just ensure it has missing values
        # self.assertIsInstance(masked_output, TensorConstant)
        assert masked_output.missing_values is not None

        return None
