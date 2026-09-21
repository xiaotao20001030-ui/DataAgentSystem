x = 10
print(type(x))

name = input("请输入名字：")
print("你好", name)

score = 80

if score >= 60:
    print("及格")
else:
    print("不及格")
for i in range(5):
    print(i)
data = [1,2,3,4]

print(data[0])
data.append(5)

student = {
    "name":"张三",
    "age":23
}

a = {1,2,2,3}

print(a)

def addd(a,b):
    return a+b
print(addd(3,4))

import numpy as np

a=np.array([1,2,3])

print(a.mean())

print(student["name"])
def add(a, b):
    return a+b


