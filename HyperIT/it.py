import numpy as np
from abc import ABC, abstractmethod
from scipy import stats
from PIL import Image, ImageDraw
from typing import Tuple, List, Union
from tqdm import tqdm
import matplotlib.pyplot as plt
import os

from jpype import isJVMStarted, getDefaultJVMPath, startJVM, JArray, JDouble, shutdownJVM, JPackage
from phyid.calculate import calc_PhiID
from phyid.utils import PhiID_atoms_abbr

class HyperIT(ABC):
    """ HyperIT: Hyperscanning Analyses using Information Theoretic Measures.

        HyperIT is equipped to compute pairwise, multivariate Mutual Information (MI), Transfer Entropy (TE), and Integrated Information Decomposition (ΦID) for continuous time-series data. 
        Compatible for both intra-brain and inter-brain analyses and for both epoched and unepoched data. 
        Multiple estimator choices and parameter customisations (via JIDT) are available, including KSG, Kernel, Gaussian, Symbolic, and Histogram/Binning. 
        Integrated statistical significance testing using permutation/boostrapping approach for most estimators. 
        Visualisations of MI/TE matrices and information atoms/lattices also provided.

    Args:
        ABC (_type_): Abstract Base Class for HyperIT.

    Note: This class requires numpy, matplotlib, PIL, jpype (with the infodynamics.jar file), and phyid as dependencies.
    """

    def __init__(self, data1: np.ndarray, data2: np.ndarray, channel_names: List[str], verbose: bool = False, working_directory: str = None):
        """ Creates HyperIT object containing time-series data and channel names for analysis. 
            Automatic data checks for consistency and dimensionality, identifying whether analysis is to be intra- or inter-brain.

            Determines whether epochality of data.
                - If data is 3 dimensional, data is assumed to be epoched with shape    (epochs, channels, time_points).
                - If data is 2 dimensional, data is assumed to be unepoched with shape          (channels, time_points).

        Args:
            data1                   (np.ndarray): Time-series data for participant 1.
            data2                   (np.ndarray): Time-series data for participant 1.
            channel_names            (List[str]): A list of strings representing the channel names for each participant. [[channel_names_p1], [channel_names_p2]] or [[channel_names_p1]] for intra-brain.
            verbose             (bool, optional): Whether constructor and analyses should output details and progress. Defaults to False.
            working_directory    (str, optional): The directory where the infodynamics.jar file is located. Defaults to None (later defaults to os.getcwd()).
        """
        self.__setup_JVM(working_directory)
        self._channel_names = channel_names #  [[p1][p2]] or [[p1]] for intra-brain
        self._channel_indices1 = []
        self._channel_indices2 = []

        self._all_data = [data1, data2]
        self._data1, self._data2 = self._all_data

        # NOTE: _data1, _data2, _channel_indices1, _channel_indices2 will be used for calculations (as these can be amended during ROI setting)

        self._roi = []
        self._roi_specified = False
        self._scale_of_organisation = 1 # 0 = global organisation (all channels), 1 = micro organisation (each channel), n = meso- or n-scale organisation (n channels)
        
        self._inter_brain: bool = not np.array_equal(data1, data2)
        self._is_epoched: bool = data1.ndim == 3
        self._initialise_parameter = None
        self.verbose: bool = verbose

        self.__check_data()

        if self.verbose:
            print("HyperIT object created successfully.")
            if self._is_epoched:
                print(f"{'Inter-Brain' if self._inter_brain else 'Intra-Brain'} analysis and epoched data detected. \nAssuming each signal has shape ({self.n_epo} epochs, {self.n_chan} channels, {self.n_samples} time points).")
            else:
                print(f"{'Inter-Brain' if self._inter_brain else 'Intra-Brain'} analysis and unepoched data detected. \nAssuming each signal has shape ({self.n_chan} channels, {self.n_samples} time points).")


    def __del__(self):
        """ Destructor for HyperIT object. Ensures JVM is shutdown upon deletion of object. """
        try:
            shutdownJVM()
            if self.verbose:
                print("JVM has been shutdown.")
        except Exception as e:
            if self.verbose:
                print(f"Error shutting down JVM: {e}")

    def __repr__(self) -> str:
        """ String representation of HyperIT object. """
        analysis_type = 'Hyperscanning' if self._inter_brain else 'Intra-Brain'
        channel_info = f"{self._channel_names[0]}"  # Assuming self._channel_names[0] is a list of channel names for the first data set
        
        # Adding second channel name if inter_brain analysis is being conducted
        if self._inter_brain:
            channel_info += f" and {self._channel_names[0][1]}"

        return (f"HyperIT Object: \n"
                f"{analysis_type} Analysis with {self.n_epo} epochs, {self.n_chan} channels, "
                f"and {self.n_samples} time points. \n"
                f"Channel names passed: \n"
                f"{channel_info}.")

    def __len__(self) -> int:
        """ Returns the number of epochs in the HyperIT object. """
        return self.n_epo
    
    def __str__(self) -> str:
        """ String representation of HyperIT object. """
        return self.__repr__()
    



    @property
    def roi(self) -> List[List[Union[str, int]]]:
        """Returns the region of interest for both data of the HyperIT object."""
        return self._roi

    @roi.setter
    def roi(self, roi_list) -> None:
        """Sets the region of interest for both data of the HyperIT object.

        Args:
            value: A list of lists, where each sublist is a region of interest containing either strings of EEG channel names or integer indices.
        
        Raises:
            ValueError: If the value is not a list of lists, if elements of the sublists are not of type str or int, or if sublists do not have the same length.
        """

        self._roi_specified = True

        ## DETERMINE SCALE OF ORGANISATION
        # 0: Global organisation (all channels)
        # 1: Micro organisation (each channel)
        # n: Meso- or n-scale organisation (n channels per roi group)

        # Check if roi is structured for pointwise channel comparison
        # e.g., roi_list = [['Fp1', 'Fp2'], ['F3', 'F4']]
        if all(isinstance(sublist, list) and not any(isinstance(item, list) for item in sublist) for sublist in roi_list):
            self._scale_of_organisation = 1 

        # Check if roi is structured for grouped channel comparison
        # e.g., roi_list = [[  ['Fp1', 'Fp2'],['CP1','CP2']  ],     n CHANNELS IN EACH GROUP FOR PARTICIPANT 1
        #                   [    ['F3', 'F4'],['F7', 'F8']   ]]     n CHANNELS IN EACH GROUP FOR PARTICIPANT 2
        elif all(isinstance(sublist, list) and all(isinstance(item, list) for item in sublist) for sublist in roi_list):
            # Ensure uniformity in the number of groups across both halves
            num_groups_x = len(roi_list[0])
            num_groups_y = len(roi_list[1])
            if num_groups_x == num_groups_y:
                self._soi_groups = num_groups_x 

                group_lengths = [len(group) for half in roi_list for group in half]
                if len(set(group_lengths)) == 1:
                    self._scale_of_organisation = group_lengths[0] 
                    self._initialise_parameter = (self._scale_of_organisation, self._scale_of_organisation)
                else:
                    raise ValueError("Not all groups have the same number of channels.")
            else:
                raise ValueError("ROI halves do not have the same number of channel groups per participant.")

        else:
            raise ValueError("ROI structure is not recognised.")
        
        if self.verbose:
            print(f"Scale of organisation: {self._scale_of_organisation} parts.")
            print(f"Groups of channels: {self._soi_groups}")

        roi1, roi2 = roi_list
        
        self._channel_indices1 = self.__convert_names_to_indices(roi1, 0) # same array as roi1 just with indices instead of EEG channel names
        self._channel_indices2 = self.__convert_names_to_indices(roi2, 1)

        # POINTWISE CHANNEL COMPARISON
        if self._scale_of_organisation == 1:
            if self._is_epoched:
                self._data1 = self._data1[:, self._channel_indices1, :]
                self._data2 = self._data2[:, self._channel_indices2, :]
            else:
                self._data1 = self._data1[self._channel_indices1, :]
                self._data2 = self._data2[self._channel_indices2, :]

            self.n_chan = len(self._channel_indices1)

        # for other scales of organisation, this will be handled in the compute_mi and compute_te functions

        self._roi = [self._channel_indices1, self._channel_indices2]
        



    def reset_roi(self) -> None:
        """Resets the region of interest for both data of the HyperIT object to all channels."""
        self._roi_specified = False
        self._scale_of_organisation = 1
        self._channel_indices1 = np.arange(len(self._channel_names[0]))
        self._channel_indices2 = np.arange(len(self._channel_names[1]) if len(self._channel_names) > 1 else len(self._channel_names[0]))
        self._roi = [self._channel_indices1, self._channel_indices2]
        self._data1, self._data2 = self._all_data
        self.n_chan = len(self._channel_indices1)
        print("Region of interest has been reset to all channels.")



    def __convert_names_to_indices(self, roi_part, participant):
        """Converts ROI channel names or groups of names into indices based on the channel list.

        Args:
            roi_part: A single ROI, list of ROIs, or list of lists of ROIs to convert.
            participant: The index of the participant (0 or 1) to match with the correct channel names list.

        Returns:
            A list of indices, or list of lists of indices, corresponding to the channel names.
        """
        channel_names = self._channel_names[participant]

        # Handle sub-sublists (grouped channel comparison)
        if all(isinstance(item, list) for item in roi_part):
            # roi_part is a list of lists
            return [[channel_names.index(name) if isinstance(name, str) else name for name in group] for group in roi_part]
        
        # Handle simple list (pointwise channel comparison)
        elif isinstance(roi_part, list):
            return [channel_names.index(name) if isinstance(name, str) else name for name in roi_part]

        # Handle single channel name or index
        elif isinstance(roi_part, str):
            return [channel_names.index(roi_part)]

        else:
            return roi_part  # In case roi_part is already in the desired format (indices)
        
    def __convert_indices_to_names(self, roi_part, participant):
        """Converts ROI channel indices or groups of indices into names based on the channel list.

        Args:
            roi_part: A single index, list of indices, or list of lists of indices to convert.
            participant: The index of the participant (0 or 1) to match with the correct channel names list.

        Returns:
            A list of names, or list of lists of names, corresponding to the channel indices.
        """
        channel_names = self._channel_names[participant]
        
        if isinstance(roi_part, np.ndarray):
            roi_part = roi_part.tolist()

        # Handle sub-sublists (grouped channel comparison)
        if all(isinstance(item, list) for item in roi_part):
            return [[channel_names[index] if isinstance(index, int) else index for index in group] for group in roi_part]

        # Handle simple list (pointwise channel comparison)
        elif isinstance(roi_part, list):
            return [channel_names[index] if isinstance(index, int) else index for index in roi_part]

        # Handle single channel index
        elif isinstance(roi_part, int):
            return channel_names[roi_part]

        else:
            return roi_part  # In case roi_part is already in the desired format (names)



    @staticmethod
    def __setup_JVM(working_directory: str = None) -> None:
        if(not isJVMStarted()):
            
            if working_directory is None:
                working_directory = os.getcwd()

            jarLocation = os.path.join(working_directory, "infodynamics.jar")

            if not os.path.isfile(jarLocation):
                    raise FileNotFoundError(f"infodynamics.jar not found (expected at {os.path.abspath(jarLocation)}).")

            startJVM(getDefaultJVMPath(), "-ea", "-Djava.class.path=" + jarLocation)


    def __check_data(self) -> None:
        """ Checks the consistency and dimensionality of the time-series data and channel names. Sets the number of epochs, channels, and time points as object variables.

        Ensures:
            - Data are numpy arrays.
            - Data shapes are consistent.
            - Data dimensions are either 2 or 3 dimensional.
            - Channel names are in correct format and match number of channels in data.
        """

        if not all(isinstance(data, np.ndarray) for data in [self._data1, self._data2]):
            raise ValueError("Time-series data must be numpy arrays.")
        
        if self._data1.shape != self._data2.shape:
            raise ValueError("Time-series data must have the same shape for both participants.")
    
        if self._data1.ndim not in [2,3]:
            raise ValueError(f"Unexpected number of dimensions in time-series data: {self._data1.ndim}. Expected 2 dimensions (channels, time_points) or 3 dimensions (epochs, channels, time_points).")

        if not isinstance(self._channel_names, (list, np.ndarray)) or isinstance(self._channel_names[0], str):
            raise ValueError("Channel names must be a list of strings or a list of lists of strings for inter-brain analysis.")
    
        if not self._inter_brain and isinstance(self._channel_names[0], list):
            self._channel_names = [self._channel_names] * 2

        if self._is_epoched:
            self.n_epo, self.n_chan, self.n_samples = self._data1.shape
        else:
            self.n_epo = 1
            self.n_chan, self.n_samples = self._data1.shape

        n_channels = self._data1.shape[1] if self._is_epoched else self._data1.shape[0]

        if any(len(names) != n_channels for names in self._channel_names):
            raise ValueError("The number of channels in time-series data does not match the length of channel_names.")
        
        self._channel_indices1 = np.arange(len(self._channel_names[0]))
        self._channel_indices2 = np.arange(len(self._channel_names[1])) if len(self._channel_names) > 1 else self._channel_indices2.copy()
        
        


    @staticmethod
    def __setup_JArray(a: np.ndarray) -> JArray:
        """ Converts a numpy array to a Java array for use in JIDT."""

        a = (a).astype(np.float64) 

        try:
            ja = JArray(JDouble, a.ndim)(a)
        except Exception: 
            ja = JArray(JDouble, a.ndim)(a.tolist())

        return ja



    def __mi_hist(self, s1: np.ndarray, s2: np.ndarray) -> float:
        """Calculates Mutual Information using Histogram/Binning Estimator for time-series signals."""

        @staticmethod
        def calc_fd_bins(X: np.ndarray, Y: np.ndarray) -> int:
            """Calculates the optimal frequency-distribution bin size for histogram estimator using Freedman-Diaconis Rule."""

            fd_bins_X = np.ceil(np.ptp(X) / (2.0 * stats.iqr(X) * len(X)**(-1/3)))
            fd_bins_Y = np.ceil(np.ptp(Y) / (2.0 * stats.iqr(Y) * len(Y)**(-1/3)))
            fd_bins = int(np.ceil((fd_bins_X+fd_bins_Y)/2))
            return fd_bins

        pairwise = np.zeros((self.n_epo, 1))

        for epo_i in range(self.n_epo):

            X, Y = (s1[epo_i, :], s2[epo_i, :]) if self._is_epoched else (s1, s2)

            j_hist, _, _ = np.histogram2d(X, Y, bins=calc_fd_bins(X, Y))
            pxy = j_hist / np.sum(j_hist)  # Joint probability distribution

            # Marginals
            px = np.sum(pxy, axis=1) 
            py = np.sum(pxy, axis=0) 

            # Entropies
            Hx = -np.sum(px * np.log2(px + np.finfo(float).eps))
            Hy = -np.sum(py * np.log2(py + np.finfo(float).eps))
            Hxy = -np.sum(pxy * np.log2(pxy + np.finfo(float).eps))

            result = Hx + Hy - Hxy

            pairwise[epo_i] = result

        return pairwise


    def __mi_symb(self, s1: np.ndarray, s2: np.ndarray, l: int = 1, m: int = 3) -> float:
        """Calculates Mutual Information using Symbolic Estimator for time-series signals."""

        symbol_weights = np.power(m, np.arange(m))
        pairwise = np.zeros((self.n_epo, 1))

        def symb_symbolise(X: np.ndarray, l: int, m: int) -> np.ndarray:
            Y = np.empty((m, len(X) - (m - 1) * l))
            for i in range(m):
                Y[i] = X[i * l:i * l + Y.shape[1]]
            return Y.T

        def symb_normalise_counts(d) -> None:
            total = sum(d.values())        
            return {key: value / total for key, value in d.items()}
        
        for epo_i in range(self.n_epo):

            X, Y = (s1[epo_i, :], s2[epo_i, :]) if self._is_epoched else (s1, s2)

            X = symb_symbolise(X, l, m).argsort(kind='quicksort')
            Y = symb_symbolise(Y, l, m).argsort(kind='quicksort')

            # multiply each symbol [1,0,3] by symbol_weights [1,3,9] => [1,0,27] and give a final array of the sum of each code ([.., .., 28, .. ])
            symbol_hash_X = (np.multiply(X, symbol_weights)).sum(1) 
            symbol_hash_Y = (np.multiply(Y, symbol_weights)).sum(1)
    

            p_xy, p_x, p_y = map(symb_normalise_counts, [dict(), dict(), dict()])
            
            for i in range(len(symbol_hash_X)-1):

                xy = f"{symbol_hash_X[i]},{symbol_hash_Y[i]}"
                x,y = str(symbol_hash_X[i]), str(symbol_hash_Y[i])

                for dict_, key in zip([p_xy, p_x, p_y], [xy, x, y]):
                    dict_[key] = dict_.get(key, 0) + 1

            # Normalise counts directly into probabilities
            p_xy, p_x, p_y = [np.array(list(symb_normalise_counts(d).values())) for d in [p_xy, p_x, p_y]]
            
            entropy_X = -np.sum(p_x * np.log2(p_x + np.finfo(float).eps)) 
            entropy_Y = -np.sum(p_y * np.log2(p_y + np.finfo(float).eps))
            entropy_XY = -np.sum(p_xy * np.log2(p_xy + np.finfo(float).eps))

            pairwise[epo_i] = entropy_X + entropy_Y - entropy_XY

        return pairwise



    def __which_mi_estimator(self) -> None:
        """Determines the Mutual Information estimator to be used based on user input. Many estimators are deployed using JIDT."""

        if self.estimator_type == 'histogram':
            self.estimator_name = 'Histogram/Binning Estimator'
            self.calc_sigstats = False # Temporary whilst I figure out how to get p-values for hist/bin estimator
            if self.verbose:
                print("Please note that p-values are not available for Histogram/Binning Estimator as this is not computed using JIDT. Work in progress...")

        elif self.estimator_type == 'ksg1' or self.estimator_type == 'ksg':
            self.estimator_name = 'KSG Estimator (version 1)'
            self.Calc = JPackage("infodynamics.measures.continuous.kraskov").MutualInfoCalculatorMultiVariateKraskov1()
            self.Calc.setProperty("k", str(self.params.get('kraskov_param', 4)))

        elif self.estimator_type == 'ksg2':
            self.estimator_name = 'KSG Estimator (version 2)'
            self.Calc = JPackage("infodynamics.measures.continuous.kraskov").MutualInfoCalculatorMultiVariateKraskov2()
            self.Calc.setProperty("k", str(self.params.get('kraskov_param', 4)))
            
        elif self.estimator_type == 'kernel':
            self.estimator_name = 'Box Kernel Estimator'
            self.Calc = JPackage("infodynamics.measures.continuous.kernel").MutualInfoCalculatorMultiVariateKernel()
            self.Calc.setProperty("KERNEL_WIDTH", str(self.params.get('kernel_width', 0.25)))

        elif self.estimator_type == 'gaussian':
            self.estimator_name = 'Gaussian Estimator'
            self.Calc = JPackage("infodynamics.measures.continuous.gaussian").MutualInfoCalculatorMultiVariateGaussian()

        elif self.estimator_type == 'symbolic':
            self.estimator_name = 'Symbolic Estimator'
            self.calc_sigstats = False # Temporary whilst I figure out how to get p-values for symbolic estimator
            if self.verbose:
                print("Please note that p-values are not available for Symbolic Estimator as this is not computed using JIDT. Work in progress...")

        else:
            raise ValueError(f"Estimator type {self.estimator_type} not supported. Please choose from 'histogram', 'ksg1', 'ksg2', 'kernel', 'gaussian', 'symbolic'.")

        if not self.estimator_type == 'histogram' and not self.estimator_type == 'symbolic':
            self.Calc.setProperty("NORMALISE", str(self.params.get('normalise', True)))


    def __which_te_estimator(self) -> None:
        """Determines the Transfer Entropy estimator to be used based on user input. Many estimators are deployed using JIDT."""

        if self.estimator_type == 'ksg' or self.estimator_type == 'ksg1' or self.estimator_type == 'ksg2':
            self.estimator_name = 'KSG Estimator'
            self.Calc = JPackage("infodynamics.measures.continuous.kraskov").TransferEntropyCalculatorMultiVariateKraskov()
            self.Calc.setProperty("k_HISTORY", str(self.params.get('k', 1)))
            self.Calc.setProperty("k_TAU", str(self.params.get('k_tau', 1)))
            self.Calc.setProperty("l_HISTORY", str(self.params.get('l', 1)))
            self.Calc.setProperty("l_TAU", str(self.params.get('l_tau', 1)))
            self.Calc.setProperty("DELAY", str(self.params.get('delay', 1)))
            self.Calc.setProperty("k", str(self.params.get('kraskov_param', 4)))
            
        elif self.estimator_type == 'kernel':
            self.estimator_name = 'Box Kernel Estimator'
            self.Calc = JPackage("infodynamics.measures.continuous.kernel").TransferEntropyCalculatorMultiVariateKernel()
            self.Calc.setProperty("KERNEL_WIDTH", str(self.params.get('kernel_width', 0.5)))

        elif self.estimator_type == 'gaussian':
            self.estimator_name = 'Gaussian Estimator'
            self.Calc = JPackage("infodynamics.measures.continuous.gaussian").TransferEntropyCalculatorMultiVariateGaussian()
            self.Calc.setProperty("k_HISTORY", str(self.params.get('k', 1)))
            self.Calc.setProperty("k_TAU", str(self.params.get('k_tau', 1)))
            self.Calc.setProperty("l_HISTORY", str(self.params.get('l', 1)))
            self.Calc.setProperty("l_TAU", str(self.params.get('l_tau', 1)))
            self.Calc.setProperty("DELAY", str(self.params.get('delay', 1)))
            self.Calc.setProperty("BIAS_CORRECTION", str(self.params.get('bias_correction', False)).lower())

        elif self.estimator_type == 'symbolic':
            self.estimator_name = 'Symbolic Estimator'
            self.Calc = JPackage("infodynamics.measures.continuous.symbolic").TransferEntropyCalculatorSymbolic()
            self.Calc.setProperty("k_HISTORY", str(self.params.get('k', 1)))
            self._initialise_parameter = (2)

        else:
            raise ValueError(f"Estimator type {self.estimator_type} not supported. Please choose from 'ksg', 'kernel', 'gaussian', or 'symbolic'.")

        self.Calc.setProperty("NORMALISE", str(self.params.get('normalise', True)).lower()) 



    def __estimate_it(self, s1: np.ndarray, s2: np.ndarray) -> np.ndarray:
        """ Estimates Mutual Information or Transfer Entropy for a pair of time-series signals using JIDT estimators. """

        estimations = np.zeros((self.n_epo, 4)) # stores MI/TE result, mean, std, p-value per epoch

        for epo_i in range(self.n_epo):
            
            X, Y = (s1[epo_i, ...], s2[epo_i, ...]) if self._is_epoched else (s1, s2)

            ## GROUPWISE; multivariate time series comparison
            if self._scale_of_organisation > 1:
                X, Y = X.T, Y.T # transpose to shape (samples, group_channels)

            # initialise parameter describes the dimensions of the data
            self.Calc.initialise(*self._initialise_parameter) if self._initialise_parameter else self.Calc.initialise()
            self.Calc.setObservations(self.__setup_JArray(X), self.__setup_JArray(Y))
            result = self.Calc.computeAverageLocalOfObservations() * np.log(2)

            if self.calc_sigstats:
                stat_sig = self.Calc.computeSignificance(self.stat_sig_perm_num)
                estimations[epo_i] = [result, stat_sig.getMeanOfDistribution(), stat_sig.getStdOfDistribution(), stat_sig.pValue]
            else:
                estimations[epo_i, 0] = result
            
        return estimations
    


    def __plot_it(self, it_matrix: np.ndarray) -> None:
        """Plots the Mutual Information or Transfer Entropy matrix for visualisation. 
        Axes labelled with source and target channel names. 
        Choice to plot for all epochs, specific epoch(s), or average across epochs.

        Args:
            it_matrix (np.ndarray): The Mutual Information or Transfer Entropy matrix to be plotted with shape (n_chan, n_chan, n_epo, 4), 
            where the last dimension represents the statistical signficance testing results: (local result, distribution mean, distribution standard deviation, p-value).
        """

        title = f'{self.measure} | {self.estimator_name} \n {"Inter-Brain" if self._inter_brain else "Intra-Brain"}'
        epochs = [0] # default to un-epoched or epoch-average case
        choice = None
        
        if self._scale_of_organisation > 1:
            source_channel_names = self.__convert_indices_to_names(self._channel_indices1, 0) if self._scale_of_organisation == 1 else self.__convert_indices_to_names(self._roi[0], 0)
            target_channel_names = self.__convert_indices_to_names(self._channel_indices2, 1) if self._scale_of_organisation == 1 else self.__convert_indices_to_names(self._roi[1], 1)

            print("Plotting for grouped channels.")

            print("Source Groups:")
            for i in range(self._soi_groups):
                print(f"{i+1}: {source_channel_names[i]}")

            print("\n\nTarget Groups:")
            for i in range(self._soi_groups):
                print(f"{i+1}: {target_channel_names[i]}")


        if self._is_epoched: 
            choice = input(f"{self.n_epo} epochs detected. Plot for \n1. All epochs \n2. Specific epoch \n3. Average MI/TE across epochs \nEnter choice: ")
            if choice == "1":
                print("Plotting for all epochs.")
                epochs = range(self.n_epo)
            elif choice == "2":
                epo_choice = input(f"Enter epoch number(s) [1 to {self.n_epo}] separated by comma only: ")
                try:
                    epochs = [int(epo)-1 for epo in epo_choice.split(',')]
                except ValueError:
                    print("Invalid input. Defaulting to plotting all epochs.")
                    epochs = range(self.n_epo)
            elif choice == "3":
                print("Plotting for average MI/TE across epochs. Note that p-values will not be shown.")
                
            else:
                print("Invalid choice. Defaulting to un-epoched data.")


        for epo_i in epochs:
            
            highest = np.max(it_matrix[:,:,epo_i,0])
            channel_pair_with_highest = np.unravel_index(np.argmax(it_matrix[:,:,epo_i,0]), it_matrix[:,:,epo_i,0].shape)
            if self.verbose:
                if self._scale_of_organisation == 1:
                    print(f"Strongest regions: (Source Channel {self.__convert_indices_to_names(self._channel_indices1, 0)[channel_pair_with_highest[0]]} --> " +
                                         f" Target Channel {self.__convert_indices_to_names(self._channel_indices2, 1)[channel_pair_with_highest[1]]}) = {highest}")
                else:
                    print(f"Strongest regions: (Source Group {source_channel_names[i]} --> Target Group {target_channel_names[i]}) = {highest}")

            plt.figure(figsize=(12, 10))
            plt.imshow(it_matrix[:,:,epo_i,0], cmap='BuPu', vmin=0, aspect='auto')

            if self._is_epoched and not choice == "3":
                plt.title(f'{title}; Epoch {epo_i+1}', pad=20)
            else:
                plt.title(title, pad=20)
                
            if self.calc_sigstats and not choice == "3" and not self.estimator_type == 'histogram' and not self.estimator_type == 'symbolic': # Again, temporary.
                for i in range(it_matrix.shape[0]):
                    for j in range(it_matrix.shape[1]):
                        p_val = float(it_matrix[i, j, epo_i, 3])
                        if p_val < self.p_threshold and (not self._inter_brain and i != j):
                            normalized_value = (it_matrix[i, j, epo_i, 0] - np.min(it_matrix[:,:,epo_i,0])) / (np.max(it_matrix[:,:,epo_i,0]) - np.min(it_matrix[:,:,epo_i,0]))
                            text_colour = 'white' if normalized_value > 0.5 else 'black'
                            plt.text(j, i, f'p={p_val:.2f}', ha='center', va='center', color=text_colour, fontsize=8, fontweight='bold')

            plt.colorbar()
            plt.xlabel('Target Channels')
            plt.ylabel('Source Channels')

            if self._scale_of_organisation == 1:
                plt.xticks(range(self.n_chan), self.__convert_indices_to_names(self._channel_indices2, 1), rotation=90) 
                plt.yticks(range(self.n_chan), self.__convert_indices_to_names(self._channel_indices1, 0))
            else:
                plt.xticks(range(self._soi_groups), [f'Group {i+1}' for i in range(self._soi_groups)], rotation=90)
                plt.yticks(range(self._soi_groups), [f'Group {i+1}' for i in range(self._soi_groups)])

            plt.tick_params(axis='x', which='both', bottom=True, top=False, labeltop=True)
            plt.tick_params(axis='y', which='both', right=False, left=False, labelleft=True)
            plt.show()


    @staticmethod
    def __plot_atoms(phi_dict: dict):
        """Plots the values of the atoms in the lattice for a given pair of channels/groups."""

        while True:
            user_input = input("Enter two source and target channel/group indices, separated by comma (or type 'done' to stop): ").split(',')
            
            if len(user_input) == 1 and user_input[0].lower() == 'done':
                break

            if len(user_input) != 2 or not all(part.strip().isdigit() for part in user_input):
                print("Invalid input. Please enter exactly two numbers separated by a comma.")
                continue

            ch_X, ch_Y = (int(part.strip()) for part in user_input)

            try:
                value_dict = phi_dict[ch_X][ch_Y]
                if value_dict is None:
                    raise KeyError

                image = Image.open('visualisations/atoms_lattice_values.png')
                draw = ImageDraw.Draw(image) 

                text_positions = {
                    'rtr': (485, 1007), 
                    'rtx': (160, 780),
                    'rty': (363, 780), 
                    'rts': (37, 512), 
                    'xtr': (610, 779), 
                    'xtx': (237, 510), 
                    'xty': (487, 585), 
                    'xts': (160, 243), 
                    'ytr': (800, 780), 
                    'ytx': (485, 427), 
                    'yty': (725, 505), 
                    'yts': (363, 243), 
                    'str': (930, 505), 
                    'stx': (605, 243), 
                    'sty': (807, 243), 
                    'sts': (485, 41)   
                }

                for text, pos in text_positions.items():
                    value = value_dict.get(text, '0')
                    plot_text = f"{round(float(value), 3):.3f}"
                    draw.text(pos, plot_text, fill="black", font_size=25)

                image.show()
            
            except KeyError:
                print("Invalid channel/group indices.")




    def compute_mi(self, estimator_type: str = 'kernel', calc_sigstats: bool = False, vis: bool = False, **kwargs) -> np.ndarray:
        """Function to compute mutual information between data (time-series signals) instantiated in the HyperIT object.

        Args:
            estimator_type       (str, optional): Which mutual information estimator to use. Defaults to 'kernel'.
            calc_sigstats       (bool, optional): Whether to conduct statistical signficance testing. Defaults to False.
            vis                 (bool, optional): Whether to visualise (via __plot_it()). Defaults to False.

        Returns:
                                    (np.ndarray): A matrix of mutual information values with shape (n_chan, n_chan, n_epo, 4),
                                                  where the last dimension represents the statistical signficance testing results: (local result, distribution mean, distribution standard deviation, p-value). 
                                                  If calc_sigstats is False, only the local results will be returned in this last dimension.
        """
        
        self.measure = 'Mutual Information'
        self.estimator_type: str = estimator_type.lower()
        self.calc_sigstats: bool = calc_sigstats
        self.vis: bool = vis
        self.params = kwargs

        self.stat_sig_perm_num = self.params.get('stat_sig_perm_num', 100)
        self.p_threshold = self.params.get('p_threshold', 0.05)
        
        self.estimator = self.__which_mi_estimator()

        if self.estimator_type == 'histogram' or self.estimator_type == 'symbolic':
            self.mi_matrix = np.zeros((self.n_chan, self.n_chan, self.n_epo, 1)) # TEMPORARY, until I figure out how to get p-values for hist/bin and symbolic MI estimators
        
        else:
            self.mi_matrix = np.zeros((self.n_chan, self.n_chan, self.n_epo, 4)) if self._scale_of_organisation == 1 else np.zeros((self._soi_groups, self._soi_groups, self.n_epo, 4))

        


        loop_range = self.n_chan if self._scale_of_organisation == 1 else self._soi_groups

        for i in tqdm(range(loop_range)):
            for j in range(loop_range):

                if self._inter_brain or i != j:

                    if self._scale_of_organisation == 1:
                        s1, s2 = (self._data1[:, i, :], self._data2[:, j, :]) if self._is_epoched else (self._data1[i, :], self._data2[j, :])
                    
                    elif self._scale_of_organisation > 1:
                        s1, s2 = (self._data1[:, self._roi[0][i], :], self._data2[:, self._roi[1][j], :]) if self._is_epoched else (self._data1[self._roi[0][i], :], self._data2[self._roi[1][j], :])

                    if self.estimator_type == 'histogram':
                        self.mi_matrix[i, j] = self.__mi_hist(s1, s2)
                    elif self.estimator_type == 'symbolic':
                        self.mi_matrix[i, j] = self.__mi_symb(s1, s2)
                    else:
                        self.mi_matrix[i, j] = self.__estimate_it(s1, s2)

                    if not self._inter_brain:
                        self.mi_matrix[j, i] = self.mi_matrix[i, j]


        mi = np.array((self.mi_matrix))

        if self.vis:
            self.__plot_it(mi)

        return mi
    
    def compute_te(self, estimator_type: str = 'kernel', calc_sigstats: bool = False, vis: bool = False, **kwargs) -> Tuple[np.ndarray, np.ndarray]:
        """Function to compute transfer entropy between data (time-series signals) instantiated in the HyperIT object. 
            data1 is first taken to be the source and data2 the target (X->Y). This function automatically computes the opposite matrix for Y -> X.

        Args:
            estimator_type       (str, optional): Which Mutual Information estimator to use. Defaults to 'kernel'.
            calc_sigstats       (bool, optional): Whether to conduct statistical signficance testing. Defaults to False.
            vis                 (bool, optional): Whether to visualise (via __plot_it()). Defaults to False.

        Returns:
                   Tuple(np.ndarray, np.ndarray): Two matrices of transfer entropy values (X->Y and Y->X), each with shape (n_chan, n_chan, n_epo, 4),
                                                  where the last dimension represents the statistical signficance testing results: (local result, distribution mean, distribution standard deviation, p-value). 
                                                  If calc_sigstats is False, only the local results will be returned in this last dimension.
        """
        
        self.measure = 'Transfer Entropy'
        self.estimator_type: str = estimator_type.lower()
        self.calc_sigstats: bool = calc_sigstats
        self.vis: bool = vis
        self.params = kwargs
        
        self.stat_sig_perm_num = self.params.get('stat_sig_perm_num', 100)
        self.p_threshold = self.params.get('p_threshold', 0.05)

        self.estimator = self.__which_te_estimator()

        self.te_matrix_xy, self.te_matrix_yx = (np.zeros((self.n_chan, self.n_chan, self.n_epo, 4)), np.zeros((self.n_chan, self.n_chan, self.n_epo, 4))) if self._scale_of_organisation == 1 else (np.zeros((self._soi_groups, self._soi_groups, self.n_epo, 4)), np.zeros((self._soi_groups, self._soi_groups, self.n_epo, 4)))

        loop_range = self.n_chan if self._scale_of_organisation == 1 else self._soi_groups

        for i in tqdm(range(loop_range)):
            for j in range(loop_range):
                
                if self._inter_brain or i != j: # avoid self-channel calculations for intra_brain condition
                    
                    if self._scale_of_organisation == 1:
                        s1, s2 = (self._data1[:, i, :], self._data2[:, j, :]) if self._is_epoched else (self._data1[i, :], self._data2[j, :])
                    
                    elif self._scale_of_organisation > 1:
                        s1, s2 = (self._data1[:, self._roi[0][i], :], self._data2[:, self._roi[1][j], :]) if self._is_epoched else (self._data1[self._roi[0][i], :], self._data2[self._roi[1][j], :])

                    self.te_matrix_xy[i, j] = self.__estimate_it(s1, s2)
                    
                    if self._inter_brain: # don't need to compute opposite matrix for intra-brain as we already loop through each channel combination including symmetric
            
                        self.te_matrix_yx[i, j] = self.__estimate_it(s2, s1)
                    
        te_xy = np.array((self.te_matrix_xy))
        te_yx = np.array((self.te_matrix_yx))
        
        if self.vis:
            print("Plotting Transfer Entropy for X -> Y...")
            self.__plot_it(te_xy)
            if self._inter_brain:
                print("Plotting Transfer Entropy for Y -> X...")
                self.__plot_it(te_yx)
                
        return te_xy, te_yx

    def compute_atoms(self, tau: int = 1, redundancy: str = 'MMI', vis: bool = False, **kwargs) -> Tuple[np.ndarray, np.ndarray]:
        """Function to compute Integrated Information Decomposition (ΦID) between data (time-series signals) instantiated in the HyperIT object.
            Option to visualise the lattice values for a specific channel pair (be sure to specify via plot_channels kwarg).

        Args:
            tau             (int, optional): Time-lag parameter. Defaults to 1.
            kind            (str, optional): Estimator type. Defaults to "gaussian".
            redundancy      (str, optional): Redundancy function to use. Defaults to 'MMI' (Minimum Mutual Information).
            vis            (bool, optional): Whether to visualise (via __plot_atoms()). Defaults to False.

        Returns:
              Tuple(np.ndarray, np.ndarray): Two matrices of Integrated Information Decomposition dictionaries (representing all atoms, both X->Y and Y->X), each with shape (n_chan, n_chan),
        """
        
        self.measure = 'Integrated Information Decomposition'


        loop_range = self.n_chan if self._scale_of_organisation == 1 else self._soi_groups

        phi_dict_xy = [[{} for _ in range(loop_range)] for _ in range(loop_range)]
        phi_dict_yx = [[{} for _ in range(loop_range)] for _ in range(loop_range)]

        for i in tqdm(range(loop_range)):
            for j in range(loop_range):
                
                if self._inter_brain or i != j:

                    if self._scale_of_organisation == 1:
                        s1, s2 = (self._data1[:, i, :], self._data2[:, j, :]) if self._is_epoched else (self._data1[i, :], self._data2[j, :])
                        if self._is_epoched:
                            s1, s2 = s1.reshape(-1), s2.reshape(-1)

                            ## If you want to pass (samples, epochs) as atomic calculations, delete line above and uncomment line below
                            # s1, s2 = s1.T, s2.T
                    
                    elif self._scale_of_organisation > 1:
                        
                        if self._is_epoched:
                            print("To compute atoms for grouped channels, please ensure that the data is not epoched. Flattening data now...")
                            
                            temp_s1, temp_s2 = self._data1[:, self._roi[0][i], :], self._data2[:, self._roi[1][j], :]
                            epoch_num = self._data1.shape[0]

                            # Flatten epochs and transpose to shape (samples, channels) [necessary configuration for phyid]
                            s1, s2 = temp_s1.transpose(1,0,2).reshape(-1, temp_s1.shape[1]), temp_s2.transpose(1,0,2).reshape(-1, temp_s2.shape[1])
                            
                        else:
                            s1, s2 = (self._data1[self._roi[0][i], :]).T, (self._data2[self._roi[1][j], :]).T

                    print(s1.shape, s2.shape)

                    atoms_results, _ = calc_PhiID(s1, s2, tau=tau, kind='gaussian', redundancy=redundancy)
                    calc_atoms = np.mean(np.array([atoms_results[_] for _ in PhiID_atoms_abbr]), axis=1)
                    phi_dict_xy[i][j] = {key: value for key, value in zip(atoms_results.keys(), calc_atoms)}

                    if self._inter_brain:
                        atoms_results, _ = calc_PhiID(s2, s1, tau=tau, kind='gaussian', redundancy=redundancy)
                        calc_atoms = np.mean(np.array([atoms_results[_] for _ in PhiID_atoms_abbr]), axis=1)
                        phi_dict_yx[i][j] = {key: value for key, value in zip(atoms_results.keys(), calc_atoms)}   

        if vis:
            self.__plot_atoms(phi_dict_xy)
            self.__plot_atoms(phi_dict_yx) 

        return phi_dict_xy, phi_dict_yx
    



if __name__ == '__main__':
    # Example usage
    data1 = np.random.randn(3, 31, 1000)
    data2 = np.random.randn(3, 31, 1000)
    channel_names = [['Fp1', 'Fp2', 'F7', 'F8', 'F3', 'F4', 'Fz', 'FT9', 'FT10', 'FC5', 'FC1', 'FC2', 'FC6', 'T7', 'C3', 'Cz', 'C4', 'T8', 'TP9', 'CP5', 'CP1', 'CP2', 'CP6', 'TP10', 'P7', 'P3', 'Pz', 'P4', 'P8', 'O1', 'O2'], 
                     ['Fp1', 'Fp2', 'F7', 'F8', 'F3', 'F4', 'Fz', 'FT9', 'FT10', 'FC5', 'FC1', 'FC2', 'FC6', 'T7', 'C3', 'Cz', 'C4', 'T8', 'TP9', 'CP5', 'CP1', 'CP2', 'CP6', 'TP10', 'P7', 'P3', 'Pz', 'P4', 'P8', 'O1', 'O2']]

    hyperit = HyperIT(data1, data2, channel_names, verbose=True)

    try:
        hyperit.roi = [[['Fp1', 'Fp2', 'F7', 'F8', 'F3', 'F4', 'Fz', 'FT9', 'FT10', 'FC5', 'FC1', 'FC2', 'FC6'],
                        ['T7', 'C3', 'Cz', 'C4', 'T8', 'TP9', 'CP5', 'CP1', 'CP2', 'CP6', 'TP10', 'P7', 'P3']], 
                        [['TP9', 'CP5', 'CP1', 'CP2', 'CP6', 'TP10', 'P7', 'P3', 'Pz', 'P4', 'P8', 'O1', 'O2'],
                         ['T7', 'C3', 'Cz', 'C4', 'T8', 'TP9', 'CP5', 'CP1', 'CP2', 'CP6', 'TP10', 'P7', 'P3']]]
        print("ROI set successfully:", hyperit.roi)
        
        # soi = 13
        # n_groups = 2

    except ValueError as e:
        print("Error setting ROI:", e)

    mi = hyperit.compute_mi(estimator_type='kernel', calc_sigstats=True, vis=True)


    # mi = hyperit.compute_mi(estimator_type='kernel', calc_sigstats=True, vis=True)
    # te_xy, te_yx = hyperit.compute_te(estimator_type='kernel', calc_sigstats=True, vis=True)
    # phi_xy, phi_yx = hyperit.compute_atoms(tau=1, redundancy='mmi', vis=True, plot_channels=[0, 0])