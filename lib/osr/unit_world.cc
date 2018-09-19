#include "unit_world.h"
#include "scene.h"
#include "cdmodel.h"
#include <iostream>
#include <glm/gtx/io.hpp>
#include <atomic>
#include <stdexcept>
#include <igl/doublearea.h>
#include <igl/cross.h>
#include <meshbool/join.h>
#include <tritri/tritri_igl.h>
#include <ode/ode.h>

namespace osr {

using std::tie;
using ArrayOfPoints = UnitWorld::ArrayOfPoints;

auto glm2Eigen(const glm::mat4& m)
{
	StateMatrix ret;
	ret.setZero();
#if 0
	for (int i = 0; i < 4; i++)
		for (int j = 0; j < 4; j++) {
			// We have to print these numbers otherwise there
			// would be errors. Probably a compiler's bug
			std::cout << m[i][j] << std::endl;
			ret(i, j) = m[j][i];
		}
	for (int i = 0; i < 4; i++)
		for (int j = 0; j < 4; j++)
			ret(i,j) = m[i][j];
#endif
	// GLM uses column major
	ret << m[0][0], m[1][0], m[2][0], m[3][0],
	       m[0][1], m[1][1], m[2][1], m[3][1],
	       m[0][2], m[1][2], m[2][2], m[3][2],
	       m[0][3], m[1][3], m[2][3], m[3][3];
	return ret;
}

struct UnitWorld::OdeData {
	static void init_ode()
	{
		static bool initialized = false;
		if (initialized)
			return ;
		dInitODE();
		dQuaternion q;
		dQSetIdentity(q);
		if (q[0] != 1.0) {
			throw std::runtime_error("ODE is not using W-first quaterion anymore!");
		}
		initialized = true;
	}

	OdeData(const CDModel& robot)
	{
		init_ode();

		world = dWorldCreate();
		space = dHashSpaceCreate(0);
		body = dBodyCreate(world);
		/*
		 * Note: alternatively we can pretend every robot is a solid
		 * sphere, which could simplify the concept and the process.
		 * 
		 * But let's try this first.
		 */
		setMass(1.0, robot);
	}

	void setMass(StateScalar mass, 
	             const CDModel& robot)
	{
#if 0
		auto com = robot.centerOfMass();
		auto MI = robot.inertiaTensor();
		dMassSetParameters(&m, 1.0, 
		                   com(0), com(1), com(2),
		                   MI(0,0), MI(1,1), MI(2,2),
		                   MI(0,1), MI(0,2), MI(1,2));
#endif
		dMassSetSphere(&m, mass, 1.0); // mass is density, radius = 1.0
		dBodySetMass(body, &m);
	}

	~OdeData()
	{
		dBodyDestroy(body);
		dSpaceDestroy(space);
		dWorldDestroy(world);
	}

	dWorldID world;
	dSpaceID space;
	dBodyID body;
	dMass m;

	void setState(const StateVector& q)
	{
		dBodySetPosition(body, q(0), q(1), q(2));
		// Note: ODE also use w-first notation
		dBodySetQuaternion(body, &q(3));
	}

	void applyForce(const ArrayOfPoints& fpos,
	                const ArrayOfPoints& fdir,
	                const Eigen::Matrix<StateScalar, -1, 1>& fmag
	               )
	{
		int N = fpos.rows();
		for (int i = 0; i < N; i++) {
			Eigen::Matrix<StateScalar, 3, 1> force;
			force = (fmag(i) * fdir.row(i)).transpose();
			dBodyAddForceAtPos(body,
			                   force(0), force(1), force(2),
			                   fpos(i,0), fpos(i,1), fpos(i,2)
			                  ); 
		}
	}

	StateVector
	stepping(StateScalar dt)
	{
		dWorldStep(world, dt);
		auto pos = dBodyGetPosition(body);
		auto quat = dBodyGetQuaternion(body);
		StateVector ret;
		ret << pos[0], pos[1], pos[2],
		       quat[0], quat[1], quat[2], quat[3];
		return ret;
	}

	void resetVelocity()
	{
		dBodySetLinearVel(body, 0, 0, 0);
		dBodySetAngularVel(body, 0, 0, 0);
	}
};


UnitWorld::UnitWorld()
{
	perturbate_.setZero();
	perturbate_(3) = 1.0;
	perturbate_tf_.setIdentity();
}

UnitWorld::~UnitWorld()
{
}

void
UnitWorld::copyFrom(const UnitWorld* other)
{
	shared_ = true;
	scene_.reset(new Scene(other->scene_));
	cd_scene_.reset(new CDModel(*scene_));
	if (other->robot_) {
		robot_.reset(new Scene(other->robot_));
		cd_robot_.reset(new CDModel(*robot_));
	} else {
		robot_.reset();
	}
	scene_scale_ = other->scene_scale_;
	calib_mat_ = glm2Eigen(scene_->getCalibrationTransform());
	inv_calib_mat_ = calib_mat_.inverse();
	perturbate_ = other->perturbate_;
}

void
UnitWorld::loadModelFromFile(const std::string& fn)
{
	scene_.reset(new Scene);
	const glm::vec3 blue(0.0f, 0.0f, 1.0f);
	scene_->load(fn, &blue);
}

void
UnitWorld::loadRobotFromFile(const std::string& fn)
{
	robot_.reset(new Scene);
	const glm::vec3 red(1.0f, 0.0f, 0.0f);
	robot_->load(fn, &red);
	robot_state_.setZero();
	robot_state_(3) = 1.0; // Quaternion for no rotation
}


void
UnitWorld::enforceRobotCenter(const StateTrans& center)
{
	robot_->overrideCenter({center(0), center(1), center(2)});
}


/*
 * scaleToUnit: calculate the scaling factor
 */
void
UnitWorld::scaleToUnit()
{
	auto scene_span =  scene_->getBoundingBox().span();
	float robot_span = 1.0f;
	if (robot_)
		robot_span =  robot_->getBoundingBox().span();
	scene_scale_ = 1.0 / std::max(scene_span, robot_span);
}


/*
 * angleModel: acutally calculate the transformation to unit world
 */
void
UnitWorld::angleModel(float latitude, float longitude)
{
	scene_->resetTransform();
	// std::cerr << "Before scale " << scene_->getCalibrationTransform() << std::endl;
	scene_->scale(glm::vec3(scene_scale_));
	// std::cerr << "After scale " << scene_->getCalibrationTransform() << std::endl;
	scene_->rotate(glm::radians(latitude), 1, 0, 0);      // latitude
	scene_->rotate(glm::radians(longitude), 0, 1, 0);     // longitude
	calib_mat_ = glm2Eigen(scene_->getCalibrationTransform());
	inv_calib_mat_ = calib_mat_.inverse();
	cd_scene_.reset(new CDModel(*scene_));
	if (robot_) {
		robot_->resetTransform();
		robot_->moveToCenter();
		robot_->scale(glm::vec3(scene_scale_));
		robot_->rotate(glm::radians(latitude), 1, 0, 0);      // latitude
		robot_->rotate(glm::radians(longitude), 0, 1, 0);     // longitude
		cd_robot_.reset(new CDModel(*robot_));
	}
}


void
UnitWorld::setPerturbation(const StateVector& pert)
{
	perturbate_ = pert;
	perturbate_tf_ = translate_state_to_transform(pert);
}

StateVector
UnitWorld::getPerturbation() const
{
	return perturbate_;
}

void
UnitWorld::setRobotState(const StateVector& state)
{
	robot_state_ = state;
}

StateVector
UnitWorld::getRobotState() const
{
	return robot_state_;
}


std::tuple<Transform, Transform>
UnitWorld::getCDTransforms(const StateVector& state) const
{
	Transform envTf;
	Transform robTf;
#if 0
	envTf = getSceneMatrix();
	robTf = translate_state_to_transform(state);
	robTf = robTf * getRobotMatrix();
#else
	// envTf.setIdentity();
	envTf = translate_state_to_transform(perturbate_); // state already contains perturbation.
	robTf = translate_state_to_transform(state);
#endif
	return std::make_tuple(envTf, robTf);
}


bool
UnitWorld::isValid(const StateVector& state) const
{
	if (!cd_scene_ || !cd_robot_)
		return true;
	Transform envTf;
	Transform robTf;
	std::tie(envTf, robTf) = getCDTransforms(state);
	// std::cerr << "CD with\n" << envTf.matrix() << "\n\n" << robTf.matrix() << "\n";
	// std::cerr << translate_state_to_matrix(state) << '\n';
	// std::cerr << robTf.matrix() << '\n';
#if 0
	Eigen::Matrix4f robTfm, envTfm;
	auto tf = robot_->transform();
	auto etf = scene_->transform();
	for (int i = 0; i < 4; i++) {
		for (int j = 0; j < 4; j++) {
			robTfm(i, j) = tf[i][j];
			envTfm(i, j) = etf[i][j];
		}
	}
	robTf = robTfm.block<3,4>(0,0);
	envTf = envTfm.block<3,4>(0,0);
	std::cerr << " Rob TF (glm):\n" << tf << "\n";
	std::cerr << " Rob TFm :\n" << robTfm << "\n";
	std::cerr << " Rob TF (before):\n" << robTf.matrix() << "\n";
#endif
#if 0
	std::cerr << " Env TF:\n" << envTf.matrix() << "\n";
	std::cerr << " Rob TF:\n" << robTf.matrix() << "\n";
#endif
	return !CDModel::collide(*cd_scene_, envTf, *cd_robot_, robTf);
}

bool UnitWorld::isDisentangled(const StateVector& state) const
{
	if (!cd_scene_ || !cd_robot_) {
		throw std::runtime_error("Pain in the ass: models not loaded");
		return true;
	}
	Transform envTf;
	Transform robTf;
#if 1
	std::tie(envTf, robTf) = getCDTransforms(state);
#else
	envTf.setIdentity();
	robTf.setIdentity();
#endif
	return !CDModel::collideBB(*cd_scene_, envTf, *cd_robot_, robTf);
}


std::tuple<StateVector, bool, float>
UnitWorld::transitState(const StateVector& state,
                       int action,
                       double transit_magnitude,
                       double verify_delta) const
{
	Eigen::Vector2f magnitudes;
	magnitudes << transit_magnitude , transit_magnitude * 2;
	Eigen::Vector2f deltas;
	deltas << verify_delta, verify_delta * 2;

	int action_type = action < kActionPerTransformType ? 0 : 1;
	if (action >= kTotalNumberOfActions) {
		/*
		 * Invalid action, return the initial state.
		 */
		return std::make_tuple(state, false, 0.0f);
	}
	if (!isValid(state)) {
		/*
		 * Invalid initial state
		 */
		std::cerr << "> Invalid Init State " << std::endl;
		return std::make_tuple(state, false, 0.0f);
	}
	auto magnitude = magnitudes(action_type);
	auto deltacap = deltas(action_type);
	float sym = action % 2 == 0 ? 1.0f : -1.0f;
	/*
	 * action (0-11) to XYZ (0-2)
	 * X: 0,1 or 6,7
	 * Y: 2,3 or 8,9
	 * Z: 4,5 or 10,11
	 */
	int axis_id = (action - kActionPerTransformType * action_type) / 2;
	StateQuat deltarot;
	StateTrans tfvec { StateTrans::Zero() };
	tfvec(axis_id) = 1.0f;
#if 1
	StateTrans trans;
	StateQuat rot;
	tie(trans, rot) = decompose(state);
	if (action_type == 0) {
		trans += deltacap * tfvec * sym;
	} else {
		Eigen::AngleAxis<StateScalar> aa(deltacap * sym, tfvec);
		rot = aa * rot;
	}
	StateVector to_state;
	to_state = compose(trans, rot);

	float current_verify_delta = verify_delta;
	// std::cerr << "> Init V Mag " << verify_delta << std::endl;
	while (true) {
		StateVector free_state;
		bool done;
		float prog;
		tie(free_state, done, prog) = transitStateTo(state, to_state, current_verify_delta);
		if (!isValid(free_state))
			throw std::runtime_error("SAN check failed, invalid state from transitStateTo");
		if (prog > 0.0 or current_verify_delta == 0.0)
			/* Sometimes vmag vanishes */
			return std::make_tuple(free_state, done, prog);
		/*
		 * A free state must be locally free, prog == 0.0 implies
		 * current verify delta is too large.
		 */
		current_verify_delta /= 2.0;
		// std::cerr << "> V Mag shrink to " << current_verify_delta << std::endl;
	}
#else
	/*
	 * Post condition:
	 *      tfvec or aa presents the delta action
	 */
	std::function<void(float)> applier;
	/* rot and trans are accumulators that would be initialized later */
	StateQuat rot;
	StateTrans trans;
	if (action_type == 0) {
		applier = [&rot, &trans, &tfvec](float delta) {
			trans += delta * tfvec;
		};
	} else {
		applier = [&rot, &trans, &tfvec, sym](float delta) {
			Eigen::AngleAxis<StateScalar> aa(delta * sym, tfvec);
			rot = aa * rot;
			rot.normalize();
		};
	}
	while (true) {
		StateVector nstate, freestate(state);
		bool done = true;
		auto accum = 0.0f;
		tie(trans, rot) = decompose(state);
		while (true) {
			float delta = std::min(deltacap, magnitude - accum);
			float naccum = accum + delta;
			applier(delta);
			nstate = compose(trans, rot);
			/*
			 * Verify the new state at accum + delta
			 */
			if (!isValid(nstate)) {
				done = false;
				break;
			}
			freestate = nstate;
			/*
			 * naccum is valid, proceed.
			 */
			accum = naccum;
			/* Exit when reaches last iteration */
			if (accum == magnitude)
				break;
		}
		if (accum > 0.0)
			break;
		/*
		 * Otherwise we need to reduce deltacap
		 */
	}
	float prog = accum / magnitude;
	return std::make_tuple(freestate, done, prog);
#endif
}


std::tuple<StateVector, bool, float>
UnitWorld::transitStateTo(const StateVector& from,
                          const StateVector& to,
                          double verify_delta) const
{
	double dist = distance(from, to);
	// std::cerr << "\t\tNSeg: " << nseg << std::endl;
#if 0 // Parallel Version
	int nseg = int(std::ceil(std::max(1.0, dist/verify_delta)));
	double rate = 1.0 / double(nseg);
	Eigen::VectorXi valid;
	valid.setZero(nseg);
	std::atomic<bool> hitInvalid(false);
	{
// #pragma omp parallel for
		for (int i = 1; i <= nseg; i++) {
			if (hitInvalid.load())
				continue;
			double tau = i * rate;
			auto state = interpolate(from, to, tau);
			if (!isValid(state)) {
				valid(i - 1) = 0;
				hitInvalid.store(true);
			} else {
				valid(i - 1) = 1;
			}
		}
	}
	for (int i = 0; i < nseg; i++) {
		if (!valid(i)) {
			/*
			 * Note: valid(0) records the validity of (i+1) * rate
			 * So i * rate is the correct tau
			 */
			double tau = i * rate;
			auto last_free = interpolate(from, to, tau);
			return std::make_tuple(last_free, false, tau);
		}
	}
#else
	StateVector last_free = from;
	double delta = verify_delta;
	if (verify_delta >= dist) {
		return std::make_tuple(from, false, 0.0);
	}
	double inv_dist = 1.0/dist;
	double last_tau = 0.0;
	while (delta <= dist) {
		double tau = delta * inv_dist;
		auto state = interpolate(from, to, tau);
		if (!isValid(state)) {
			return std::make_tuple(last_free, false, last_tau);
		}
		last_tau = tau;
		last_free = state;
		if (delta < dist) {
			delta += verify_delta;
			delta = std::min(dist, delta);
		} else {
			delta += verify_delta;
		}
	}
#endif
	return std::make_tuple(last_free, delta > dist, last_tau);
}


bool
UnitWorld::isValidTransition(const StateVector& from,
                             const StateVector& to,
                             double initial_verify_delta) const
{
	double d = distance(from, to);
	auto vdelta = std::min(d / 2.0, initial_verify_delta);
	auto tup = transitStateTo(from, to, vdelta);
	return std::get<1>(tup);
}


std::tuple<StateVector, bool, float>
UnitWorld::transitStateBy(const StateVector& from,
	                  const StateTrans& tr,
	                  const AngleAxisVector& aav,
	                  double verify_delta) const
{
	StateTrans base;
	base << from(0), from(1), from(2);
	base += tr;
	StateQuat rot(from(3), from(4), from(5), from(6));
	Eigen::AngleAxis<StateScalar> aa(aav.norm(), aav.normalized());
	rot = aa * rot;
	StateVector to;
	to << base(0), base(1), base(2),
	      rot.w(), rot.x(),
	      rot.y(), rot.z();
	return transitStateTo(from, to ,verify_delta);
}


StateMatrix
UnitWorld::getSceneMatrix() const
{
	if (!scene_)
		return StateMatrix::Identity();
	return glm2Eigen(scene_->getCalibrationTransform());
}

StateMatrix
UnitWorld::getRobotMatrix() const
{
	if (!robot_)
		return StateMatrix::Identity();
	return glm2Eigen(robot_->getCalibrationTransform());
}


StateVector
UnitWorld::translateToUnitState(const StateVector& state)
{
#if 1
	Eigen::Vector4d t(state(0), state(1), state(2), 1.0f);
	Eigen::Vector4d nt = calib_mat_ * t;
	StateVector ret;
	ret << nt(0), nt(1), nt(2),
               state(3), state(4), state(5), state(6);
	return applyPertubation(ret);
#else
	return state;
#endif
}

StateVector
UnitWorld::translateFromUnitState(const StateVector& pstate)
{
#if 1
	auto state = unapplyPertubation(pstate);
	Eigen::Vector4d t(state(0), state(1), state(2), 1.0f);
	Eigen::Vector4d nt = inv_calib_mat_ * t;
	StateVector ret;
	ret << nt(0), nt(1), nt(2),
               state(3), state(4), state(5), state(6);
	return ret;
#else
	return state;
#endif
}

StateVector
UnitWorld::applyPertubation(const StateVector& state)
{
	StateQuat rot, prot;
	StateTrans trans, ptrans;
	std::tie(trans, rot) = decompose(state);
	std::tie(ptrans, prot) = decompose(perturbate_);

	StateQuat qret = prot * rot;
	StateTrans tret = ptrans + prot.toRotationMatrix() * trans;
	return compose(tret, qret);
}

StateVector
UnitWorld::unapplyPertubation(const StateVector& state)
{
	StateQuat rot, prot;
	StateTrans trans, ptrans;
	std::tie(trans, rot) = decompose(state);
	std::tie(ptrans, prot) = decompose(perturbate_);

	StateQuat qret = prot.inverse();
	StateTrans tret = qret.toRotationMatrix() * (-ptrans + trans);
	qret *= rot;
	return compose(tret, qret);
}

Eigen::Matrix<int, -1, -1>
UnitWorld::calculateVisibilityMatrix(ArrayOfStates qs,
                                     bool is_unit_states,
                                     double verify_magnitude)
{
	int N = qs.rows();
	if (!is_unit_states) {
#pragma omp parallel for
		for (int i = 0; i < N; i++)
			qs.row(i) = translateToUnitState(qs.row(i)).transpose();
	}
	Eigen::Matrix<int, -1, -1> ret;
	ret.resize(N, N);
#pragma omp parallel for
	for (int fi = 0; fi < N; fi++) {
		for (int ti = fi + 1; ti < N; ti++) {
			int valid = !!isValidTransition(qs.row(fi), qs.row(ti), verify_magnitude);
			ret(fi, ti) = valid;
			ret(ti, fi) = valid;
		}
	}
	return ret;
}

Eigen::Matrix<int, -1, -1>
UnitWorld::calculateVisibilityMatrix2(ArrayOfStates qs0,
                                      bool qs0_is_unit_states,
                                      ArrayOfStates qs1,
                                      bool qs1_is_unit_states,
                                      double verify_magnitude)
{
	int M = qs0.rows();
	int N = qs1.rows();
	if (!qs0_is_unit_states)
#pragma omp parallel for
		for (int i = 0; i < M; i++)
			qs0.row(i) = translateToUnitState(qs0.row(i)).transpose();
	if (!qs1_is_unit_states)
#pragma omp parallel for
		for (int i = 0; i < N; i++)
			qs1.row(i) = translateToUnitState(qs1.row(i)).transpose();
	Eigen::Matrix<int, -1, -1> ret;
	ret.resize(M, N);
	std::atomic<int> prog(0);
#pragma omp parallel for
	for (int fi = 0; fi < M; fi++) {
		for (int ti = 0; ti < N; ti++) {
			int valid = isValidTransition(qs0.row(fi), qs1.row(ti), verify_magnitude);
			ret(fi, ti) = valid;
		}
		prog++;
		if (omp_get_thread_num() == 0) {
			std::cerr << "Progress: " << prog << "/" << M << std::endl;
		}
	}
	return ret;
}

Eigen::Matrix<StateScalar, -1, 1>
UnitWorld::intersectionRegionSurfaceAreas(ArrayOfStates qs,
                                          bool qs_are_unit_states)
{
	ArrayOfStates qsu = ppToUnitStates(qs, qs_are_unit_states);
	int Nq = qs.rows();
	Eigen::Matrix<StateScalar, -1, 1> ret;
	ret.setZero(Nq);

	Transform envTf = std::get<0>(getCDTransforms(robot_state_));

	CDModel::VMatrix env_V = (envTf * cd_scene_->vertices().transpose()).transpose();
	auto env_F = cd_scene_->faces();

	auto rob_F = cd_robot_->faces();

	for (int i = 0; i < Nq; i++) {
		StateVector state = qs.row(i).transpose();
		Transform robTf = translate_state_to_transform(state);
		CDModel::VMatrix rob_V = (robTf * cd_robot_->vertices().transpose()).transpose();

		CDModel::VMatrix RV;
		CDModel::FMatrix RF;
		mesh_bool(env_V, env_F,
			  rob_V, rob_F,
			  igl::MESH_BOOLEAN_TYPE_INTERSECT,
			  RV, RF);
		Eigen::VectorXd areas;
		igl::doublearea(RV, RF, areas);
		ret(i) = areas.sum();
	}
	return ret;
}

std::tuple<
	ArrayOfPoints, // Position
	ArrayOfPoints, // Force vector
	Eigen::Matrix<StateScalar, -1, 1>,                // Force magnititude
	Eigen::Matrix<int, -1, 2>                         // Pairs of triangle indices
>
UnitWorld::intersectingSegments(StateVector unitq)
{
	ArrayOfPoints ret_pos, ret_vec;
	Eigen::Matrix<StateScalar, -1, 1> ret_mag;
	Eigen::Matrix<int, -1, 2> face_pairs;

	Transform env_tf;
	Transform rob_tf;
	std::tie(env_tf, rob_tf) = getCDTransforms(unitq);
	if (!CDModel::collideForDetails(*cd_scene_, env_tf, *cd_robot_, rob_tf, face_pairs)) {
		return std::tie(ret_pos, ret_vec, ret_mag, face_pairs);
	}
#if 0
	std::cerr << "debug: face pairs\n" << face_pairs << std::endl;
#endif
	CDModel::VMatrix env_V = (env_tf * cd_scene_->vertices().transpose()).transpose();
	CDModel::VMatrix rob_V = (rob_tf * cd_robot_->vertices().transpose()).transpose();
	auto env_F = cd_scene_->faces();
	auto rob_F = cd_robot_->faces();
	Eigen::Matrix<StateScalar, -1, 6> col_segs;
	Eigen::Matrix<int, -1, 1> coplanars;
	// NOTE: The (rob, env) order should be the same as calling
	// CDModel::collideForDetails
	tritri::TriTri(env_V, env_F,
	               rob_V, rob_F,
	               face_pairs,
	               col_segs, coplanars);
	int m = col_segs.rows();
	ret_pos = col_segs.block(0, 0, m, 3);
	ret_vec = col_segs.block(0, 3, m, 3);
	ret_mag = (ret_vec - ret_pos).array().square().rowwise().sum().sqrt().matrix(); // L2 norm per row
#if 0
	ret_pos = 0.5 * (col_segs.block(0, 0, m, 3) + col_segs.block(0, 3, m, 3));
	ret_vec = col_segs.block(0, 0, m, 3) - col_segs.block(0, 3, m, 3);
	for (int i = 0; i < m; i++) {
		// Face Normals (UNnormalized)
		Eigen::Vector3i rob_face = rob_F.row(face_pairs(i, 0));
		Eigen::Vector3i env_face = env_F.row(face_pairs(i, 0));
		Eigen::Vector3d rob_fn = (rob_V.row(rob_face(1)) - rob_V.row(rob_face(0))).cross(rob_V.row(rob_face(2)) - rob_V.row(rob_face(0)));
		Eigen::Vector3d env_fn = (env_V.row(env_face(1)) - env_V.row(env_face(0))).cross(env_V.row(env_face(2)) - env_V.row(env_face(0)));
		// Rational: force should be orthogonal w.r.t. intersecting
		// line segment and the robot's face normal (since robot is
		// movable)
		ret_vec.row(i) = rob_fn.cross(ret_vec.row(i)).normalized();
	}
#endif
	return std::tie(ret_pos, ret_vec, ret_mag, face_pairs);
}

ArrayOfPoints
UnitWorld::getRobotFaceNormalsFromIndices(const Eigen::Matrix<int, -1, 1>& faces)
{
	return cd_robot_->faceNormals(faces);
}

ArrayOfPoints
UnitWorld::getRobotFaceNormalsFromIndices(const Eigen::Matrix<int, -1, 2>& faces)
{
	return cd_robot_->faceNormals(faces.col(1));
}

ArrayOfPoints
UnitWorld::getSceneFaceNormalsFromIndices(const Eigen::Matrix<int, -1, 1>& faces)
{
	return cd_scene_->faceNormals(faces);
}

ArrayOfPoints
UnitWorld::getSceneFaceNormalsFromIndices(const Eigen::Matrix<int, -1, 2>& faces)
{
	return cd_scene_->faceNormals(faces.col(0));
}

std::tuple<
	ArrayOfPoints, // Force apply position
	ArrayOfPoints  // Force direction
>
UnitWorld::forceDirectionFromIntersectingSegments(
	const ArrayOfPoints& sbegins,
	const ArrayOfPoints& sends,
	const Eigen::Matrix<int, -1, 2> faces)
{
	ArrayOfPoints ret_pos, ret_dir;
	ret_pos = (sbegins + sends) * 0.5;
	ArrayOfPoints svec = sends - sbegins;
	igl::cross(svec, getRobotFaceNormalsFromIndices(faces), ret_dir);
	Eigen::Matrix<StateScalar, -1, 3> enormal = getSceneFaceNormalsFromIndices(faces);
	Eigen::Array<StateScalar, -1, 1> dots = (ret_dir.array() * enormal.array()).rowwise().sum().sign();

	ret_dir = ret_dir.array().colwise() * dots;

	return std::tie(ret_pos, ret_dir);
}

ArrayOfStates
UnitWorld::ppToUnitStates(const ArrayOfStates& qs,
                          bool qs_are_unit_states)
{
	if (qs_are_unit_states)
		return qs;
	ArrayOfStates qsu(qs.rows(), qs.cols());
	for (int i = 0; i < qs.rows(); i++)
		qsu.row(i) = translateToUnitState(qs.row(i));
	return qsu;
}

StateVector
UnitWorld::pushRobot(const StateVector& unitq,
                     const ArrayOfPoints& fpos,                     // Force apply position
                     const ArrayOfPoints& fdir,                     // Force direction
                     const Eigen::Matrix<StateScalar, -1, 1>& fmag, // Force magnititude
                     StateScalar mass,
                     StateScalar dtime,                             // Durition
                     bool resetVelocity
                    )
{
	if (!ode_) {
		ode_.reset(new OdeData(*cd_robot_));
	}
	if (resetVelocity)
		ode_->resetVelocity();
	ode_->setMass(mass, *cd_robot_);
	ode_->setState(unitq);
	ode_->applyForce(fpos, fdir, fmag);
	return ode_->stepping(dtime);
}

}
