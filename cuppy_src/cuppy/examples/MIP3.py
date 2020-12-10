numVars = 2
numCons = 4
A = [[-1, 1],
     [1, -3],
     [7, -3],
     [-3, 7]]
b = [0, 0, 18, 8]
c = [1, 1]
sense = ('Max', '<=')
integerIndices = [0, 1]
#points = [[0, 0], [2, 2], [3.75, 2.75], [3, 1]]

cuts = [
#        [1, 1],
        [-.266, 2.4],
        [-1.33, 4],
        [1.33, 4],
        [4, 1.33], 
        [0.7619, 2.2857],
        [4.3174, 3.4708],
#        [0.0625, 5.1925],
#        [1.9396, 4.6863],
#        [1.4384, 2.5817],
#        [1.4334, 0.5073],
        ]
rhs = [
#       6,
        4.6,
        5,
        15,
        17.66, 
        7.5714,
        23.2751,
#       13.2561,
#       17.7056,
#       10.1052,
#       5.1093,
        ]

if __name__ == '__main__':

    try:
        from coinor.cuppy.cuttingPlanes import solve, gomoryCut
        from coinor.cuppy.milpInstance import MILPInstance
    except ImportError:
        from src.cuppy.cuttingPlanes import solve, gomoryCut
        from src.cuppy.milpInstance import MILPInstance

    m = MILPInstance(A = A, b = b, c = c,  
                     sense = sense, integerIndices = integerIndices,
                     numVars = numVars)
    
    solve(m, whichCuts = [(gomoryCut, {})], display = True, debug_print = True)
