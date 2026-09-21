# 返回多个值（实际是元组）
def min_max(nums):
    return min(nums), max(nums)


lo, hi = min_max([3, 1, 4, 1, 5, 9])
print(lo, hi)  # 1 9


# 无返回语句则返回 None
def log(msg):
    print(msg)


result = log("hi")  # 打印 hi
print(result)

x = 10  # 全局变量


def outer():
    x = 20  # 局部变量

    def inner():
        nonlocal x  # 引用外层函数的变量
        x = 30

    inner()
    print(x)  # 30


outer()
print(x)  # 10（全局变量未变）


# 使用 global 修改全局变量
def change_global():
    global x
    x = 100


change_global()
print(x)  # 100
# None

# 语法：lambda 参数: 表达式
square = lambda x: x ** 2
print(square(5))  # 25

# 配合 sorted / map / filter
nums = [3, 1, 4, 1, 5, 9]
print(sorted(nums, key=lambda x: -x))  # [9, 5, 4, 3, 1, 1]

squared = list(map(lambda x: x ** 2, nums))
evens = list(filter(lambda x: x % 2 == 0, nums))
print(evens)
print(squared)


import time

def timer(func):
    """计算函数执行时间的装饰器"""
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        print(f"{func.__name__} 耗时 {time.time() - start:.4f}s")
        return result
    return wrapper

@timer
def slow_function():
    time.sleep(1)
    return "done"

slow_function()
# 输出: slow_function 耗时 1.0001s