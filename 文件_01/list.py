# s = [56, 90, 88, "A", "Hello"]
#
# print(type(s))
#
# print(s[0])
# print(s[-2])
#
# print(s[-1])
#
# s.insert(-2, "B")
# print(s)
#
# s.remove("B")
# print(s)
#
# e = s.pop(1)
# print(e)
# s.sort()
# print(s)
# s.reverse()
# print(s)

# numList = [1, 2, 3, 4, 5, 6, 7, 8, 9]
# numList2 = [4, 5, 6, 7, 8, 9, 45]
# # print(numList)
# # for num in numList:
# #     numList2.append(num)
# # newline = []
# # for num in numList2:
# #     if num not in numList:
# #         newline.append(num)
# #
# # print(newline)
#
# # num_list3 = []
# # for num in range(1, 21):
# #     num_list3.append(num ** 2)
# # print(num_list3)
#
# num_list4 = [i ** 2 for i in range(1, 21)]
#
# print(num_list4)
#
# num_list5 = [i ** 2 for i in range(1, 21) if i % 2 == 0]
#
# s = "Hello-Python"
# print(s[4])
# print(s[-8])
#
# for i in s:
#     print(i)
#
# print(s[0:5:1])
# print(s[:5:1])
# print(s[:1:])
# print(s[:1])
#
#
# sr = s.split("-")
# print(sr)
#
#
#
#
# t1 = ( 80,43,34,56,56,67)
# print(t1)
# print(t1[0])
# print(t1.index(80))
#
#
# print(t1.count(34))

# t1 = (1,2,3,4,5,6,7,8,9)
# t2 = (4,4)
#
# a, b, c, d, e, f, g, h, i = t1
# print(a)
# print(b)
#
# g,*h,f  = t1;
# print(h)

t3 = {1, 2, 3, 4, 5, 6, 7, 8, 9}
t4 = {6, 7, 8, 9}
print(t3.difference(t4))
print(t3 - t4)
print({s for s in t3 if s not in t4})
print(t3 & t4)
print(t3 | t4)
