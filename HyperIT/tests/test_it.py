import unittest
from unittest.mock import MagicMock, patch
import numpy as np
from hyperit import HyperIT 
from utils import convert_names_to_indices
import os

class TestHyperIT(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.jarLocation = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'infodynamics.jar')
        HyperIT.setup_JVM(cls.jarLocation, verbose=True)

    def setUp(self):
        """Set up test variables used in the tests."""
        self.channels = [['C1', 'C2', 'C3'], ['C1', 'C2', 'C3']]
        self.data1 = np.random.rand(10, 3, 600)  # 10 epochs, 3 channels, 100 samples
        self.data2 = np.random.rand(10, 3, 600)
        self.freq_bands = {'alpha': (8, 12)}
        self.sfreq = 256  # Hz

    @patch('hyperit.HyperIT.setup_JVM')
    def test_initialization(self, mock_setup_jvm):
        """Test object initialization and JVM setup call."""
        hyperit_instance = HyperIT(data1=self.data1, 
                                   data2=self.data2, 
                                   channel_names=self.channels, 
                                   sfreq=self.sfreq, 
                                   freq_bands=self.freq_bands)
        mock_setup_jvm.assert_not_called()
        self.assertEqual(hyperit_instance._sfreq, self.sfreq)

    def test_check_data_valid(self):
        """Test the data validation logic with correct input."""
        try:
            HyperIT(self.data1, self.data2, self.channels, self.sfreq, self.freq_bands)
        except Exception as e:
            self.fail(f"Initialization failed with correct data: {e}")

    def test_check_data_invalid_shape(self):
        """Test the data validation logic with incorrect input shapes."""
        data_wrong = np.random.rand(5, 100)  # Wrong shape
        with self.assertRaises(ValueError):
            HyperIT(data_wrong, data_wrong, self.channels, self.sfreq, self.freq_bands)

    @patch('hyperit.HyperIT.roi', new_callable=property)
    def test_roi_setting(self, mock_roi):
        """Test setting ROI correctly assigns indices."""
        mock_roi.return_value = [[0, 1], [1, 2]]
        hyperit_instance = HyperIT(self.data1, self.data2, self.channels, self.sfreq, self.freq_bands)
        hyperit_instance.roi = [['C1', 'C2'], ['C2', 'C3']]
        self.assertEqual(hyperit_instance.roi, [[0, 1], [1, 2]])
        mock_roi.assert_called_once()

    @patch('hyperit.HyperIT.reset_roi', side_effect=lambda: [[0, 1, 2], [0, 1, 2]])
    def test_reset_roi(self, mock_reset_roi):
        """Test resetting ROI to all channels."""
        hyperit_instance = HyperIT(self.data1, self.data2, self.channels, self.sfreq, self.freq_bands)
        hyperit_instance.reset_roi()
        expected_roi = [np.arange(3), np.arange(3)]
        self.assertTrue(np.array_equal(hyperit_instance.roi[0], expected_roi[0]) and
                        np.array_equal(hyperit_instance.roi[1], expected_roi[1]))
        mock_reset_roi.assert_called_once()

    @patch('hyperit.np.histogram2d', return_value=(np.zeros((10, 10)), None, None))
    @patch('hyperit.stats.iqr', return_value=1.0)
    def test_mi_computation(self, mock_hist, mock_iqr):
        """Test Mutual Information computation."""
        hyperit_instance = HyperIT(self.data1, self.data2, self.channels, self.sfreq, self.freq_bands)
        hyperit_instance.compute_mi('histogram')
        self.assertIsNotNone(hyperit_instance.mi_matrix)
        self.assertTrue(mock_hist.called)
        self.assertTrue(mock_iqr.called)

    @patch('hyperit.setup_JArray', return_value=None)
    @patch('hyperit.set_estimator', return_value=('kernel', MagicMock(), {'prop1': 'value1'}, (2,)))
    def test_te_computation(self, mock_set_estimator, mock_jarray):
        """Test Transfer Entropy computation setup."""
        hyperit_instance = HyperIT(self.data1, self.data2, self.channels, self.sfreq, self.freq_bands)
        te_xy, te_yx = hyperit_instance.compute_te('kernel')
        self.assertIsNotNone(te_xy)
        self.assertIsNotNone(te_yx)
        self.assertTrue(mock_set_estimator.called)
        self.assertEqual(mock_set_estimator.call_args[0], ('kernel', 'te', {}))

    @patch('hyperit.calc_PhiID', return_value=({}, None))
    def test_phiid_computation(self, mock_phiid):
        """Test Integrated Information Decomposition computation."""
        hyperit_instance = HyperIT(self.data1, self.data2, self.channels, self.sfreq, self.freq_bands)
        phi_xy, phi_yx = hyperit_instance.compute_atoms()
        self.assertIsNotNone(phi_xy)
        self.assertIsNotNone(phi_yx)
        self.assertTrue(mock_phiid.called)

    @patch('builtins.input', return_value='1')  # Simulates choosing "1. All epochs"
    def test_plotting(self, mock_plot_show):
        """Test the plotting function calls."""
        hyperit_instance = HyperIT(self.data1, self.data2, self.channels, self.sfreq, self.freq_bands)
        hyperit_instance.compute_mi('histogram', vis=True)
        mock_plot_show.assert_called()

    def tearDown(self):
        """Clean up any mock patches to prevent leaks between tests."""
        patch.stopall()



class TestConvertNamesToIndices(unittest.TestCase):

    def setUp(self):
        self.channel_names = [['C1', 'C2', 'C3', 'C4'], ['C1', 'C2', 'C3', 'C4']]

    def test_grouped_comparison(self):
        roi = [['C1', 'C3'], ['C2', 'C4']]
        expected = [[0, 2], [1, 3]]
        result = convert_names_to_indices(self.channel_names, roi, 1)
        self.assertEqual(result, expected)

    def test_pointwise_comparison(self):
        roi = ['C2', 'C3']
        expected = [1, 2]
        result = convert_names_to_indices(self.channel_names, roi, 0)
        self.assertEqual(result, expected)

    def test_single_channel(self):
        roi = 'C3'
        expected = [2]
        result = convert_names_to_indices(self.channel_names, roi, 0)
        self.assertEqual(result, expected)

    def test_direct_index_input(self):
        roi = [1, 2]
        expected = [1, 2]
        result = convert_names_to_indices(self.channel_names, roi, 0)
        self.assertEqual(result, expected)

    def test_invalid_channel_name(self):
        roi = ['C5']  # Does not exist in participant 0's list
        with self.assertRaises(ValueError):
            convert_names_to_indices(self.channel_names, roi, 0)

if __name__ == '__main__':
    unittest.main()
