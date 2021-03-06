/**
 * SPDX-FileCopyrightText: Copyright © 2020 The University of Texas at Austin
 * SPDX-FileContributor: Xinya Zhang <xinyazhang@utexas.edu>
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef LEVELSET_GRID_H
#define LEVELSET_GRID_H

#include <Eigen/Core>
#include <string>

namespace levelset {

	void generate(
			const Eigen::MatrixXf& V,
			const Eigen::MatrixXi& F,
			double mtov_width,
			double vtom_width,
			const std::string& fn
		     );

};

#endif
