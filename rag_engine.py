# rag_engine.py
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HUB_OFFLINE'] = '1'
import json
import chromadb
from sentence_transformers import SentenceTransformer

# 防止下载卡死
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'


class JobRAG:
    def __init__(self, data_path="jobs_data.json"):
        print("  [RAG] 正在初始化岗位数据库...")
        # 加载模型
        self.embed_model = SentenceTransformer('BAAI/bge-small-zh-v1.5')
        self.client = chromadb.Client()

        # 每次运行重置一下集合，防止重复
        try:
            self.client.delete_collection(name="jobs")
        except:
            pass
        self.collection = self.client.create_collection(name="jobs")

        # 加载数据并入库
        with open(data_path, "r", encoding="utf-8") as f:
            jobs = json.load(f)

        documents = []
        metadatas = []
        ids = []
        for job in jobs:
            # 把公司、岗位、要求拼成一段文本用于向量化
            text = f"公司：{job['company']}。岗位：{job['title']}。城市：{job['city']}。要求：{job['requirements']}"
            documents.append(text)
            metadatas.append({"company": job['company'], "title": job['title'], "city": job['city']})
            ids.append(job['id'])

        self.collection.add(documents=documents, metadatas=metadatas, ids=ids)
        print(f"  [RAG] 成功入库 {len(documents)} 条岗位信息！")

    def search(self, query: str, top_k: int = 2) -> str:
        """根据用户的求职意向，检索最相关的岗位"""
        results = self.collection.query(query_texts=[query], n_results=top_k)

        if not results['documents'] or not results['documents'][0]:
            return "未找到匹配的岗位。"

        # 拼接检索结果
        retrieved_text = "为您找到以下相关岗位：\n"
        for i in range(len(results['documents'][0])):
            doc = results['documents'][0][i]
            meta = results['metadatas'][0][i]
            retrieved_text += f"{i + 1}. 【{meta['company']} - {meta['title']} ({meta['city']})】\n   {doc}\n"

        return retrieved_text