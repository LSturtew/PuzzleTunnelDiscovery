/**
 * SPDX-FileCopyrightText: Copyright © 2020 The University of Texas at Austin
 * SPDX-FileContributor: Xinya Zhang <xinyazhang@utexas.edu>
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "sancheck.h"
#include <igl/point_mesh_squared_distance.h>
#include <iostream>

void san_check(
	const Eigen::MatrixXf& IV,
	const Eigen::MatrixXi& IF,
	const Eigen::MatrixXf& OV,
	const Eigen::MatrixXi& OF,
	double expected_distance
	)
{
	double sqexpd = expected_distance * expected_distance;
	Eigen::MatrixXf C;
	Eigen::VectorXi I;
	Eigen::VectorXf sqrD;
	std::cerr << "This SANCHECK is disabled due to bugs in libigl (#595)\n";
	return ;
	// igl::point_mesh_squared_distance(OV, IV, IF, sqrD, I, C);
	Eigen::ArrayXf array = sqrD.array();
	float sq = array.mean();
	double stddev = std::sqrt(sq - sqexpd);
	double ratio = stddev/expected_distance;
	if (ratio < 0.05)
		std::cerr << "Pass\n";
	else
		std::cerr << "Failed\n";
	std::cerr << "\tstddev: " << stddev << std::endl;
	std::cerr << "\tstddev ratio: " << ratio << std::endl;
	// std::cerr << "\tSqrted Distance: " << sqrD << std::endl;
}
