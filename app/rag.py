import json
import math
import re
from pathlib import Path

from rank_bm25 import BM25Okapi

TOKEN = re.compile(r"[a-z0-9]+")
DAR = re.compile(r"dar\s*global")
STOP = set("a an and are as at be by for from has have how i in is it its of on or that the this to was what when where which who will with you your do does can me my about tell show".split())


def tokenize(text):
    text = DAR.sub("darglobal", text.lower())
    return [w for w in TOKEN.findall(text) if w not in STOP]


def chunk_words(text, size=170, overlap=40):
    words = text.split()
    step = size - overlap
    return [" ".join(words[i:i + size]) for i in range(0, max(len(words), 1), step) if words[i:i + size]]


class BM25(BM25Okapi):
    """BM25 with a Lucene-style IDF that stays positive, even for terms present in most chunks."""

    def _calc_idf(self, nd):
        for word, freq in nd.items():
            self.idf[word] = math.log(1 + (self.corpus_size - freq + 0.5) / (freq + 0.5))


class Index:
    def __init__(self):
        self.chunks, self.bm25 = [], None

    @property
    def ready(self):
        return self.bm25 is not None

    def load(self, path):
        path = Path(path)
        if not path.exists():
            return
        for page in json.loads(path.read_text(encoding="utf-8")):
            for piece in chunk_words(page["text"]):
                self.chunks.append({"site": page["site"], "url": page["url"], "title": page["title"], "text": piece})
        if self.chunks:
            self.bm25 = BM25([tokenize(c["site"] + " " + c["title"] + " " + c["text"]) for c in self.chunks])

    def search(self, query, k=6):
        tokens = tokenize(query)
        if not self.ready or not tokens:
            return []
        q = DAR.sub("darglobal", query.lower())
        wants_dar, wants_was = "darglobal" in q, "wasalt" in q
        scores = self.bm25.get_scores(tokens)
        ranked = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)
        ranked = [i for i in ranked if scores[i] > 0]

        # Question names exactly one company: search only that company's pages.
        if wants_dar != wants_was:
            site = "DarGlobal" if wants_dar else "Wasalt"
            return [self.chunks[i] for i in ranked if self.chunks[i]["site"] == site][:k]

        # Otherwise make sure each site gets a fair share of the results.
        picked = []
        for site in sorted({c["site"] for c in self.chunks}):
            picked += [i for i in ranked if self.chunks[i]["site"] == site][: k // 3]
        for i in ranked:
            if len(picked) >= k:
                break
            if i not in picked:
                picked.append(i)
        picked.sort(key=scores.__getitem__, reverse=True)
        return [self.chunks[i] for i in picked[:k]]
