/*
 Copyright (c) 2017 Xinya Zhang (xinyazhang at utexas dot edu)

 Copyright (c) 2011 Khaled Mamou (kmamou at gmail dot com)
 All rights reserved.
 
 Redistribution and use in source and binary forms, with or without
 modification, are permitted provided that the following conditions are met:
 
 1. Redistributions of source code must retain the above copyright notice,
 this list of conditions and the following disclaimer.
 
 2. Redistributions in binary form must reproduce the above copyright notice,
 this list of conditions and the following disclaimer in the documentation
 and/or other materials provided with the distribution.
 
 3. The names of the contributors may not be used to endorse or promote
 products derived from this software without specific prior written
 permission.
 
 THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
 LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
 CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
 SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
 CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 POSSIBILITY OF SUCH DAMAGE.
 */

#include <algorithm>
#include <assert.h>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdio.h>
#include <string.h>
#include <string>
#include <vector>
#include "intersect.h"

//#define _CRTDBG_MAP_ALLOC

#ifdef _CRTDBG_MAP_ALLOC
#include <crtdbg.h>
#include <stdlib.h>
#endif // _CRTDBG_MAP_ALLOC

#include <VHACD.h>

using namespace VHACD;
using namespace std;

class MyCallback : public IVHACD::IUserCallback {
public:
    MyCallback(void) {}
    ~MyCallback(){};
    void Update(const double overallProgress, const double stageProgress, const double operationProgress,
        const char* const stage, const char* const operation)
    {
        cout << setfill(' ') << setw(3) << (int)(overallProgress + 0.5) << "% "
             << "[ " << stage << " " << setfill(' ') << setw(3) << (int)(stageProgress + 0.5) << "% ] "
             << operation << " " << setfill(' ') << setw(3) << (int)(operationProgress + 0.5) << "%" << endl;
    };
};

class MyLogger : public IVHACD::IUserLogger {
public:
    MyLogger(void) {}
    MyLogger(const string& fileName) { OpenFile(fileName); }
    ~MyLogger(){};
    void Log(const char* const msg)
    {
        if (m_file.is_open()) {
            m_file << msg;
            m_file.flush();
        }
    }
    void OpenFile(const string& fileName)
    {
        m_file.open(fileName.c_str());
    }

private:
    ofstream m_file;
};
struct Parameters {
    unsigned int m_oclPlatformID;
    unsigned int m_oclDeviceID;
    string m_fileNameIn;
    string m_fileNameOut;
    string m_fileNameLog;
    bool m_run;
    IVHACD::Parameters m_paramsVHACD;
    Parameters(void)
    {
        m_run = true;
        m_oclPlatformID = 0;
        m_oclDeviceID = 0;
        m_fileNameIn = "";
        m_fileNameOut = "output.wrl";
        m_fileNameLog = "log.txt";
    }
};
bool LoadOFF(const string& fileName, vector<double>& points, vector<int>& triangles, IVHACD::IUserLogger& logger);
bool LoadOBJ(const string& fileName, vector<double>& points, vector<int>& triangles, IVHACD::IUserLogger& logger);
void GetFileExtension(const string& fileName, string& fileExtension);
void Usage(const Parameters& params);
void ParseParameters(int argc, char* argv[], Parameters& params);

int main(int argc, char* argv[])
{
	// --input camel.off --output camel_acd.wrl --log log.txt --resolution 1000000 --depth 20 --concavity 0.0025 --planeDownsampling 4 --convexhullDownsampling 4 --alpha 0.05 --beta 0.05 --gamma 0.00125 --pca 0 --mode 0 --maxNumVerticesPerCH 256 --minVolumePerCH 0.0001 --convexhullApproximation 1 --oclDeviceID 2
	{
		// set parameters
		Parameters params;
		ParseParameters(argc, argv, params);
		MyCallback myCallback;
		MyLogger myLogger(params.m_fileNameLog);
		params.m_paramsVHACD.m_logger = &myLogger;
		params.m_paramsVHACD.m_callback = &myCallback;
		Usage(params);
		if (!params.m_run) {
			return 0;
		}

		std::ostringstream msg;
		msg << "+ OpenCL (OFF)" << std::endl;

#ifdef _OPENMP
		msg << "+ OpenMP (ON)" << std::endl;
#else
		msg << "+ OpenMP (OFF)" << std::endl;
#endif
		msg << "+ Parameters" << std::endl;
		msg << "\t input                                       " << params.m_fileNameIn << endl;
		msg << "\t resolution                                  " << params.m_paramsVHACD.m_resolution << endl;
		msg << "\t max. concavity                              " << params.m_paramsVHACD.m_concavity << endl;
		msg << "\t plane down-sampling                         " << params.m_paramsVHACD.m_planeDownsampling << endl;
		msg << "\t convex-hull down-sampling                   " << params.m_paramsVHACD.m_convexhullDownsampling << endl;
		msg << "\t alpha                                       " << params.m_paramsVHACD.m_alpha << endl;
		msg << "\t beta                                        " << params.m_paramsVHACD.m_beta << endl;
		msg << "\t pca                                         " << params.m_paramsVHACD.m_pca << endl;
		msg << "\t mode                                        " << params.m_paramsVHACD.m_mode << endl;
		msg << "\t max. vertices per convex-hull               " << params.m_paramsVHACD.m_maxNumVerticesPerCH << endl;
		msg << "\t min. volume to add vertices to convex-hulls " << params.m_paramsVHACD.m_minVolumePerCH << endl;
		msg << "\t convex-hull approximation                   " << params.m_paramsVHACD.m_convexhullApproximation << endl;
		msg << "\t output                                      " << params.m_fileNameOut << endl;
		msg << "\t log                                         " << params.m_fileNameLog << endl;
		msg << "+ Load mesh" << std::endl;
		myLogger.Log(msg.str().c_str());

		cout << msg.str().c_str();

		// load mesh
		vector<double> points;
		vector<int> triangles;
		string fileExtension;
		GetFileExtension(params.m_fileNameIn, fileExtension);
		if (fileExtension == ".OFF") {
			if (!LoadOFF(params.m_fileNameIn, points, triangles, myLogger)) {
				return -1;
			}
		} else if (fileExtension == ".OBJ") {
			if (!LoadOBJ(params.m_fileNameIn, points, triangles, myLogger)) {
				return -1;
			}
		} else {
			myLogger.Log("Unsuppored format.\n");
			return -1;
		}

		// run V-HACD
		IVHACD* interfaceVHACD = CreateVHACD();

		bool res = interfaceVHACD->Compute(&points[0], (unsigned int)points.size() / 3,
				(const uint32_t *)&triangles[0], (unsigned int)triangles.size() / 3, params.m_paramsVHACD);

		if (res) {
			unsigned int nConvexHulls = interfaceVHACD->GetNConvexHulls();
			msg.str("");
			msg << "+ Generate output: " << nConvexHulls << " convex-hulls " << endl;
			myLogger.Log(msg.str().c_str());
			IVHACD::ConvexHull ch;
			for (unsigned int p = 0; p < nConvexHulls; ++p) {
				interfaceVHACD->GetConvexHull(p, ch);
				cout << "\tProcessing Hull " << p << " ...";
				mesh_intersect_out(params.m_fileNameOut, p,
						points.data(), points.size()/3,
						triangles.data(), triangles.size()/3,
						ch.m_points, ch.m_nPoints,
						(int*)ch.m_triangles, ch.m_nTriangles);
				cout << "Done\n";
			}
		} else {
			myLogger.Log("Decomposition cancelled.\n");
		}

		interfaceVHACD->Clean();
		interfaceVHACD->Release();
	}
#ifdef _CRTDBG_MAP_ALLOC
	_CrtDumpMemoryLeaks();
#endif // _CRTDBG_MAP_ALLOC
	return 0;
}

void Usage(const Parameters& params)
{
    std::ostringstream msg;
    msg << "V-HACD V" << VHACD_VERSION_MAJOR << "." << VHACD_VERSION_MINOR << endl;
    msg << "Syntax: convexpp [options] --input infile.obj --output outfile.wrl --log logfile.txt" << endl
        << endl;
    msg << "Options:" << endl;
    msg << "       --input                     Wavefront .obj input file name" << endl;
    msg << "       --output                    VRML 2.0 output file name" << endl;
    msg << "       --log                       Log file name" << endl;
    msg << "       --resolution                Maximum number of voxels generated during the voxelization stage (default=100,000, range=10,000-16,000,000)" << endl;
    msg << "       --concavity                 Maximum allowed concavity (default=0.0025, range=0.0-1.0)" << endl;
    msg << "       --planeDownsampling         Controls the granularity of the search for the \"best\" clipping plane (default=4, range=1-16)" << endl;
    msg << "       --convexhullDownsampling    Controls the precision of the convex-hull generation process during the clipping plane selection stage (default=4, range=1-16)" << endl;
    msg << "       --alpha                     Controls the bias toward clipping along symmetry planes (default=0.05, range=0.0-1.0)" << endl;
    msg << "       --beta                      Controls the bias toward clipping along revolution axes (default=0.05, range=0.0-1.0)" << endl;
    msg << "       --delta                     Controls the bias toward maximaxing local concavity (default=0.05, range=0.0-1.0)" << endl;
    msg << "       --pca                       Enable/disable normalizing the mesh before applying the convex decomposition (default=0, range={0,1})" << endl;
    msg << "       --mode                      0: voxel-based approximate convex decomposition, 1: tetrahedron-based approximate convex decomposition (default=0, range={0,1})" << endl;
    msg << "       --maxNumVerticesPerCH       Controls the maximum number of triangles per convex-hull (default=64, range=4-1024)" << endl;
    msg << "       --minVolumePerCH            Controls the adaptive sampling of the generated convex-hulls (default=0.0001, range=0.0-0.01)" << endl;
    msg << "       --convexhullApproximation   Enable/disable approximation when computing convex-hulls (default=1, range={0,1})" << endl;
    msg << "       --help                      Print usage" << endl
        << endl;
    msg << "Examples:" << endl;
    msg << "       testVHACD.exe --input bunny.obj --output bunny_acd.wrl --log log.txt" << endl
        << endl;
    cout << msg.str();
    if (params.m_paramsVHACD.m_logger) {
        params.m_paramsVHACD.m_logger->Log(msg.str().c_str());
    }
}

void ParseParameters(int argc, char* argv[], Parameters& params)
{
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--input")) {
            if (++i < argc)
                params.m_fileNameIn = argv[i];
        }
        else if (!strcmp(argv[i], "--output")) {
            if (++i < argc)
                params.m_fileNameOut = argv[i];
        }
        else if (!strcmp(argv[i], "--log")) {
            if (++i < argc)
                params.m_fileNameLog = argv[i];
        }
        else if (!strcmp(argv[i], "--resolution")) {
            if (++i < argc)
                params.m_paramsVHACD.m_resolution = atoi(argv[i]);
        }
        else if (!strcmp(argv[i], "--concavity")) {
            if (++i < argc)
                params.m_paramsVHACD.m_concavity = atof(argv[i]);
        }
        else if (!strcmp(argv[i], "--planeDownsampling")) {
            if (++i < argc)
                params.m_paramsVHACD.m_planeDownsampling = atoi(argv[i]);
        }
        else if (!strcmp(argv[i], "--convexhullDownsampling")) {
            if (++i < argc)
                params.m_paramsVHACD.m_convexhullDownsampling = atoi(argv[i]);
        }
        else if (!strcmp(argv[i], "--alpha")) {
            if (++i < argc)
                params.m_paramsVHACD.m_alpha = atof(argv[i]);
        }
        else if (!strcmp(argv[i], "--beta")) {
            if (++i < argc)
                params.m_paramsVHACD.m_beta = atof(argv[i]);
        }
        else if (!strcmp(argv[i], "--pca")) {
            if (++i < argc)
                params.m_paramsVHACD.m_pca = atoi(argv[i]);
        }
        else if (!strcmp(argv[i], "--mode")) {
            if (++i < argc)
                params.m_paramsVHACD.m_mode = atoi(argv[i]);
        }
        else if (!strcmp(argv[i], "--maxNumVerticesPerCH")) {
            if (++i < argc)
                params.m_paramsVHACD.m_maxNumVerticesPerCH = atoi(argv[i]);
        }
        else if (!strcmp(argv[i], "--minVolumePerCH")) {
            if (++i < argc)
                params.m_paramsVHACD.m_minVolumePerCH = atof(argv[i]);
        }
        else if (!strcmp(argv[i], "--convexhullApproximation")) {
            if (++i < argc)
                params.m_paramsVHACD.m_convexhullApproximation = atoi(argv[i]);
        }
        else if (!strcmp(argv[i], "--help")) {
            params.m_run = false;
        }
    }
    params.m_paramsVHACD.m_resolution = (params.m_paramsVHACD.m_resolution < 64) ? 0 : params.m_paramsVHACD.m_resolution;
    params.m_paramsVHACD.m_planeDownsampling = (params.m_paramsVHACD.m_planeDownsampling < 1) ? 1 : params.m_paramsVHACD.m_planeDownsampling;
    params.m_paramsVHACD.m_convexhullDownsampling = (params.m_paramsVHACD.m_convexhullDownsampling < 1) ? 1 : params.m_paramsVHACD.m_convexhullDownsampling;
}

void GetFileExtension(const string& fileName, string& fileExtension)
{
    size_t lastDotPosition = fileName.find_last_of(".");
    if (lastDotPosition == string::npos) {
        fileExtension = "";
    }
    else {
        fileExtension = fileName.substr(lastDotPosition, fileName.size());
        transform(fileExtension.begin(), fileExtension.end(), fileExtension.begin(), ::toupper);
    }
}

bool LoadOFF(const string& fileName, vector<double>& points, vector<int>& triangles, IVHACD::IUserLogger& logger)
{
    FILE* fid = fopen(fileName.c_str(), "r");
    if (fid) {
        const string strOFF("OFF");
        char temp[1024];
        (void)fscanf(fid, "%s", temp);
        if (string(temp) != strOFF) {
            logger.Log("Loading error: format not recognized \n");
            fclose(fid);
            return false;
        }
        else {
            int nv = 0;
            int nf = 0;
            int ne = 0;
            (void)fscanf(fid, "%i", &nv);
            (void)fscanf(fid, "%i", &nf);
            (void)fscanf(fid, "%i", &ne);
            points.resize(nv * 3);
            triangles.resize(nf * 3);
            const int np = nv * 3;
            for (int p = 0; p < np; p++) {
                (void)fscanf(fid, "%lf", &(points[p]));
            }
            int s;
            for (int t = 0, r = 0; t < nf; ++t) {
                (void)fscanf(fid, "%i", &s);
                if (s == 3) {
                    (void)fscanf(fid, "%i", &(triangles[r++]));
                    (void)fscanf(fid, "%i", &(triangles[r++]));
                    (void)fscanf(fid, "%i", &(triangles[r++]));
                }
                else // Fix me: support only triangular meshes
                {
                    for (int h = 0; h < s; ++h)
                        (void)fscanf(fid, "%i", &s);
                }
            }
            fclose(fid);
        }
    }
    else {
        logger.Log("Loading error: file not found \n");
        return false;
    }
    return true;
}

bool LoadOBJ(const string& fileName, vector<double>& points, vector<int>& triangles, IVHACD::IUserLogger& logger)
{
    const unsigned int BufferSize = 1024;
    FILE* fid = fopen(fileName.c_str(), "r");

    if (fid) {
        char buffer[BufferSize];
        int ip[4];
        double x[3];
        char* pch;
        char* str;
        while (!feof(fid)) {
            if (!fgets(buffer, BufferSize, fid)) {
                break;
            }
            else if (buffer[0] == 'v') {
                if (buffer[1] == ' ') {
                    str = buffer + 2;
                    for (int k = 0; k < 3; ++k) {
                        pch = strtok(str, " ");
                        if (pch)
                            x[k] = atof(pch);
                        else {
                            return false;
                        }
                        str = NULL;
                    }
                    points.push_back(x[0]);
                    points.push_back(x[1]);
                    points.push_back(x[2]);
                }
            }
            else if (buffer[0] == 'f') {

                pch = str = buffer + 2;
                int k = 0;
                while (pch) {
                    pch = strtok(str, " ");
                    if (pch && *pch != '\n') {
                        ip[k++] = atoi(pch) - 1;
                    }
                    else {
                        break;
                    }
                    str = NULL;
                }
                if (k == 3) {
                    triangles.push_back(ip[0]);
                    triangles.push_back(ip[1]);
                    triangles.push_back(ip[2]);
                }
                else if (k == 4) {
                    triangles.push_back(ip[0]);
                    triangles.push_back(ip[1]);
                    triangles.push_back(ip[2]);

                    triangles.push_back(ip[0]);
                    triangles.push_back(ip[2]);
                    triangles.push_back(ip[3]);
                }
            }
        }
        fclose(fid);
    }
    else {
        logger.Log("File not found\n");
        return false;
    }
    return true;
}
