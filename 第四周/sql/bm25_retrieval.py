from rank_bm25 import BM25Okapi


# 模拟数据库列的描述信息
schema_documents = [
    {
        "column_id": "student.id",
        "text": "student id 学生唯一标识"
    },
    {
        "column_id": "student.name",
        "text": "student name 学生姓名"
    },
    {
        "column_id": "student.age",
        "text": "student age 学生年龄"
    },
    {
        "column_id": "score.student_id",
        "text": "score student_id 学生标识 关联学生表"
    },
    {
        "column_id": "score.subject",
        "text": "score subject 考试科目"
    },
    {
        "column_id": "score.score",
        "text": "score score 考试分数 成绩"
    }
]


def tokenize(text):
    """
    简单分词：
    统一转换成小写，并按照空格切分。

    正式实验中，应使用适合中英文混合文本的分词策略。
    """
    return text.lower().split()


# 为每个列文档建立索引
tokenized_documents = [
    tokenize(item["text"])
    for item in schema_documents
]

bm25 = BM25Okapi(tokenized_documents)


def retrieve_columns(question, k=5):
    """
    根据自然语言问题检索最相关的数据库列。

    参数：
        question：用户的问题
        k：返回前 k 个结果
    """
    query_tokens = tokenize(question)

    # 计算查询与所有候选列的 BM25 分数
    scores = bm25.get_scores(query_tokens)

    # 按相关性从高到低排序
    ranked_indices = sorted(
        range(len(scores)),
        key=lambda index: scores[index],
        reverse=True
    )

    results = []

    for index in ranked_indices[:k]:
        results.append({
            "column_id": schema_documents[index]["column_id"],
            "score": float(scores[index])
        })

    return results


if __name__ == "__main__":
    question = "查询学生的姓名和考试成绩"

    results = retrieve_columns(question, k=5)

    for rank, result in enumerate(results, start=1):
        print(
            rank,
            result["column_id"],
            result["score"]
        )