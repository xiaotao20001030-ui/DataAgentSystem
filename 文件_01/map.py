dict1 = {"王林": 675, "应静静": 27}
# dict2 = {}
# dict3 = dict()
print(dict1)
dict1["王林"]  = 900
print(type(dict1))
print(dict1.items())
print(dict1.keys())
print(dict1.values())
for k, v in dict1.items():
    print(k, v)

