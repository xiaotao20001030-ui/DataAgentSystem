# num = 114.12
# print(type("Hello"))
#
# print(type(10))
# print(type(11))
# print(type(True))
# print(type(None))
# print(isinstance(num, int))
# print(isinstance(num, float))
# print(isinstance(num, complex))
#
# s1 = "Hello"
# print("大家好 我是%s,今年%s岁，学习的专业%s 爱好%s" % (2, "你是", "软件工程", "篮球"))
#
# total = 1000
# name = input("请输入你的姓名")
# age = input("请输入你的年龄")
#
# print(f"你的姓名是{name},年龄为:{age}")
#
# password = input("请输入你的密码")
# print(f"密码正确，{password}")
# num = input("请输入你的取款金额: ")
#
# print(f"取款后应行卡余额为:{total - int(num)}");
from pandas.core.computation import scope

# //为小数 /除为整数 幂指数**
# x = int(input("请输入x的值："))
# y = int(input("请输入y的值: "))
#
# print("x+y= ", x + y);
# print("x-y= ", x - y);
# n = int(input("请输入n"))
#
# print(f"{n}不在10-20之间 ", n < 10 or n > 10)
#
# score = 700
# if score >= 90:
#     print("欢迎你来清华")
#
# match score:
#     case 90:
#         print("90")
#     case 80:
#         print("80")
#     case 70:
#         print("70")
#     case _:
#         print("34")
#
# if score > 0:
#     print(f"{score}是一个正数")
# elif score < 0:
#     print(f"{score}是一个整数")
# else:
#     print(f"{score}是0")
#
#     i = 0;
#     while i < score:
#         print(i)
#         i += 1
#     else:
#         print("结束")
# msg = "Hello"
# for char in msg:
#     print(char)
# else:
#     print("结束")
#
# for i in range(1, 101, 2):
#     print(i)

for i in range(1, 10):
    for j in range(1, i + 1):
        print(f"{j} x {i} = {j * i}", end="\t")
    print()
import random

random_num = random.randint(1, 10)

num = int(input("请输入一个数字： "))

if num > random_num:
    print("")
elif num < random_num:
    print("  ")
else:
    print("  ")
