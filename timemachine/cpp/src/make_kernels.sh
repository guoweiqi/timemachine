# nvcc -std=c++11 --use_fast_math  --ptxas-options=-v -lineinfo -O3 -arch=sm_61 -Xcompiler -fPIC -I ~/Code/timemachine/timemachine/cpu_functionals/ gpu/custom_bonded_gpu.cu  gpu/custom_nonbonded_gpu.cu gpu/potential.cu -c

nvcc -std=c++11 --ptxas-options=-v -lineinfo -O2 -arch=sm_61 -Xcompiler -fPIC -I gpu/ -I optimizers/ gpu/custom_bonded_gpu.cu gpu/custom_nonbonded_gpu.cu gpu/potential.cu optimizers/optimizer.cu optimizers/langevin.cu optimizers/gpu_utils.cu optimizers/context.cu -c

# g++ -O3 -march=native -Wall -shared -std=c++11 -fPIC $PLATFORM_FLAGS `python3 -m pybind11 --includes` -L/usr/local/cuda/lib64/ -I/usr/local/cuda/include/ wrap_kernels.cpp custom_bonded_gpu.o custom_nonbonded_gpu.o potential.o -o custom_ops`python3-config --extension-suffix` -lcurand -lcublas -lcudart


g++ -O3 -march=native -Wall -shared -std=c++11 -fPIC $PLATFORM_FLAGS `python3 -m pybind11 --includes` -I gpu/ -I optimizers/ -L/usr/local/cuda/lib64/ -I/usr/local/cuda/include/ wrap_kernels.cpp custom_bonded_gpu.o custom_nonbonded_gpu.o langevin.o optimizer.o potential.o gpu_utils.o context.o -o custom_ops`python3-config --extension-suffix` -lcurand -lcublas -lcudart
