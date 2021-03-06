/**
 * SPDX-FileCopyrightText: Copyright © 2020 The University of Texas at Austin
 * SPDX-FileContributor: Xinya Zhang <xinyazhang@utexas.edu>
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef OFF_SCREEN_RENDERING_TO_H
#define OFF_SCREEN_RENDERING_TO_H

#if GPU_ENABLED

#include "osr_state.h"
#include "unit_world.h"
#include "quickgl.h"
#include <string>
#include <ostream>
#include <memory>
#include <stdint.h>
#include <tuple>
#include <vector>

#include <glm/mat4x4.hpp>

namespace osr {

class SceneRenderer;
class Camera;
class RtTexture;
class FrameBuffer;
using RtTexturePtr = std::shared_ptr<RtTexture>;
using FbPtr = std::shared_ptr<FrameBuffer>;

/*
 * osr::Renderer
 *
 *      This class loads robot and environment model, and render them to
 *      buffers. At the same time, it is also responsible for collision
 *      detection (CD).
 *
 *      Only support rigid body for now.
 *
 *      TODO: We may want a better name because CD is also handled by this
 *      class.
 */
class Renderer : public UnitWorld {
public:
	static const uint32_t NO_SCENE_RENDERING = (1 << 0);
	static const uint32_t NO_ROBOT_RENDERING = (1 << 1);
	static const uint32_t HAS_NTR_RENDERING = (1 << 2);
	// When set, the mapping of each texel in the texture atlas to primitive ID in the mesh
	// will be stored at mvpid
	static const uint32_t UV_MAPPINNG_RENDERING = (1 << 3);
	// When set, the face normal of each pixel in the framebuffer will be
	// stored at mvnormal
	static const uint32_t NORMAL_RENDERING = (1 << 4);
	// When set, the UV coordinates of the each pixel will be
	// stored at mvuv
	static const uint32_t UV_FEEDBACK = (1 << 5); 
	/*
	 * Define type for framebuffer attributes.
	 */
	typedef Eigen::Matrix<float, -1, -1, Eigen::RowMajor> RMMatrixXf;
	typedef Eigen::Matrix<uint8_t, -1, -1, Eigen::RowMajor> RMMatrixXb;
	typedef Eigen::Matrix<int32_t, -1, -1, Eigen::RowMajor> RMMatrixXi;

	Renderer();
	~Renderer();

	void setup();
	void setupFrom(const Renderer*);
	void loadModelFromFile(const std::string& fn) override;
	void loadRobotFromFile(const std::string& fn) override;
	void loadRobotTextureImage(std::string tex_fn);
	void teardown();
	void angleCamera(float latitude, float longitude);

	void render_depth_to(std::ostream& fout);
	Eigen::VectorXf render_depth_to_buffer();
	RMMatrixXf render_mvdepth_to_buffer();
	void render_mvrgbd(uint32_t flags = 0);

	RMMatrixXb mvrgb;
	RMMatrixXf mvdepth;
	RMMatrixXf mvuv;
	RMMatrixXi mvpid;
	RMMatrixXf mvnormal;

	int pbufferWidth = 224;
	int pbufferHeight = 224;
	float default_depth = 5.0f;
	GLboolean avi = false; // AdVanced Illumination
	GLboolean flat_surface = false; // Calculate normal
	Eigen::Vector3f light_position = {0.0f, 5.0f, 0.0f};

	/*
	 * Set this variable to use multple view rendering.
	 * Protocol:
	 *      Row K: View K
	 *        Column 0: latitude;
	 *        Column 1: longitude
	 */
	Eigen::MatrixXf views;

	Eigen::MatrixXf getPermutationToWorld(int view);

	static const uint32_t BARY_RENDERING_ROBOT = 0;
	static const uint32_t BARY_RENDERING_SCENE = 1;

	void addBarycentric(const UnitWorld::FMatrix& F,
	                    const UnitWorld::VMatrix& V,
	                    uint32_t target,
	                    float weight = 1.0);

	void clearBarycentric(uint32_t target);

	RMMatrixXf
	renderBarycentric(uint32_t target,
	                  Eigen::Vector2i res,
	                  const std::string& svg_fn = std::string());

	/*
	 * We may scale the whole scene as the final transformation
	 * within model transformation.
	 * 
	 * We expect this makes the NN insensitive to scaling.
	 */
	void setFinalScaling(const ScaleVector& scale);
	ScaleVector getFinalScaling() const;
private:
	void setupNonSharedObjects();

	GLuint shaderProgram = 0;
	GLuint rgbdShaderProgram = 0;
	// GLuint depthbufferID = 0;
	FbPtr depth_only_fb_; // GLuint framebufferID = 0;
	FbPtr rgbd_fb_; // GLuint rgbdFramebuffer = 0;
	RtTexturePtr depth_tex_; // GLuint renderTarget = 0;
	RtTexturePtr rgb_tex_; // GLuint rgbTarget = 0;

	std::shared_ptr<SceneRenderer> scene_renderer_;
	std::shared_ptr<SceneRenderer> robot_renderer_;

	void render_depth();
	void render_rgbd(uint32_t flags);
	Camera setup_camera(uint32_t flags);

	glm::mat4 camera_rot_;

	RtTexturePtr uv_tex_;
	RtTexturePtr pid_tex_;

	/*
	 * Code to support barycentric rendering
	 */
	using BaryUV = Eigen::Matrix<float, -1, 2, Eigen::RowMajor>;
	using BaryBary = Eigen::Matrix<float, -1, 3, Eigen::RowMajor>;
	using BaryWeight = Eigen::Matrix<float, 1, -1, Eigen::RowMajor>;

	struct BaryRenderData {
		std::vector<BaryUV> uv_array;
		std::vector<BaryBary> bary_array;
		std::vector<BaryWeight> weight_array;

		BaryUV cache_uv;
		BaryBary cache_bary;
		BaryWeight cache_weight;

		void sync(); // update cache
		void clear();
	};
	BaryRenderData brds_[2];
	std::shared_ptr<Scene> getBaryTarget(uint32_t);

	RtTexturePtr bary_tex_;
	FbPtr bary_fb_;

	GLuint bary_vs_ = 0;
	GLuint bary_gs_ = 0;
	GLuint bary_fs_ = 0;
	GLuint bary_shader_program_ = 0;
	GLuint bary_vao_ = 0;
	GLuint bary_vbo_uv_ = 0;
	GLuint bary_vbo_bary_ = 0;
	GLuint bary_vbo_weight_ = 0;
	GLuint bary_ibo_ = 0;

	StateTrans final_scaling_;

	RtTexturePtr normal_tex_;
};

}

#endif // GPU_ENABLED

#endif // OFF_SCREEN_RENDERING_TO_H
