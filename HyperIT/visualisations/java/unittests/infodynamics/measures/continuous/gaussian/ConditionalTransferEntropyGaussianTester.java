/*
 *  Java Information Dynamics Toolkit (JIDT)
 *  Copyright (C) 2012, Joseph T. Lizier
 *  
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, either version 3 of the License, or
 *  (at your option) any later version.
 *  
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *  
 *  You should have received a copy of the GNU General Public License
 *  along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

package infodynamics.measures.continuous.gaussian;

import infodynamics.measures.continuous.ConditionalTransferEntropyAbstractTester;

public class ConditionalTransferEntropyGaussianTester extends
	ConditionalTransferEntropyAbstractTester {

	public void testUnivariateMethodSignatureFails() throws Exception {
		ConditionalTransferEntropyCalculatorGaussian teCalc = new ConditionalTransferEntropyCalculatorGaussian();
		super.testUnivariateCallFailsIfWrongInitialisation(teCalc);
	}
	
	public void testLocalsAverageCorrectly() throws Exception {
		ConditionalTransferEntropyCalculatorGaussian teCalc = new ConditionalTransferEntropyCalculatorGaussian();
		super.testLocalsAverageCorrectly(teCalc, 100, 2);
	}

	public void testComputeSignificanceDoesntAlterAverage() throws Exception {
		ConditionalTransferEntropyCalculatorGaussian teCalc = new ConditionalTransferEntropyCalculatorGaussian();
		super.testComputeSignificanceDoesntAlterAverage(teCalc, 100, 2);
	}

	public void testAgainstApparentTE() throws Exception {
		TransferEntropyCalculatorGaussian teCalc = new TransferEntropyCalculatorGaussian();
		ConditionalTransferEntropyCalculatorGaussian condTeCalc = new ConditionalTransferEntropyCalculatorGaussian();
		testConditionalAgainstOrdinaryTE(teCalc, condTeCalc, 100, 2);
		testConditionalAgainstOrdinaryTE(teCalc, condTeCalc, 100, 3);
		testConditionalAgainstOrdinaryTE(teCalc, condTeCalc, 100, 4);
	}
}
