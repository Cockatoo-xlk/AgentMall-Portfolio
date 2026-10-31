"""Same NFKC + jieba search segmentation for documents and queries; no HMM drift."""

import logging
import re
import unicodedata
from functools import lru_cache

import jieba

from agentmall.retrieval.embedding import ROOT

TOKENIZER_VERSION = "jieba-0.42.1-search-nfkc-v1"
STOP = frozenset(
    (
        "的 了 呢 吗 啊 我 你 您 有 没有 有没有 想 要 请 一些 一个 "
        "可以 是否 使用 适合 比较 什么 怎么"
    ).split()
)


@lru_cache(maxsize=1)
def tokenizer():
    cache = ROOT / ".ml-cache"
    cache.mkdir(exist_ok=True)
    jieba.setLogLevel(logging.ERROR)
    segmenter = jieba.Tokenizer()
    segmenter.tmp_dir = str(cache)
    segmenter.initialize()
    return segmenter


def tokens(value: str) -> list[str]:
    value = unicodedata.normalize("NFKC", value).lower()
    # Only letters/numbers/CJK reach tsquery; punctuation cannot become operators.
    return list(
        dict.fromkeys(
            t
            for t in tokenizer().cut_for_search(value, HMM=False)
            if re.fullmatch(r"[a-z0-9\u3400-\u9fff]+", t) and t not in STOP
        )
    )[:256]


def document_tokens(value):
    return " ".join(tokens(value))


def query_tokens(value):
    return " | ".join(tokens(value))
