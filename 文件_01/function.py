from unicodedata import name


def outline():
    print("---------")


num = 100


def rectangle(l, w):
    """
   根据长方形长度宽度 计算长方形的面积
    :param l:  长度
    :param w: 宽度
    :return: 返回值
    """
    global num
    num += w
    print("---------")
    return l * w


print(rectangle(4, 5))
print(num)


def ref_stu(name, age, gender, city: "上海"):
    print(f"注册成功，姓名:{num},年龄:{age},性别:{gender}")
    return {"name": name, "age": age, "gender": gender, "city": city}



