import numpy as np

import pandas as pd
def calculate():
    data = np.array([1,2,3,4,5])
    return data.mean()


import matplotlib.pyplot as plt

x=[1,2,3]
y=[2,4,6]

plt.plot(x,y)
plt.show()
def main():
    result = calculate()
    print("平均值:", result)


if __name__ == "__main__":
    main()