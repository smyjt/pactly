import logging
from dataclasses import dataclass

import tiktoken

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    index: int
    content: str
    token_count: int


class ChunkingService:
    def __init__(
        self,
        chunk_size: int = 500,
        overlap: int = 50,
        encoding_name: str = "cl100k_base",
    ):
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.encoding = tiktoken.get_encoding(encoding_name)

    def chunk(self, text: str) -> list[Chunk]:
        """Split text into overlapping token-based chunks.

        Each chunk is chunk_size tokens. Consecutive chunks share the last
        `overlap` tokens so clauses that straddle a boundary appear in both
        adjacent chunks and won't be missed during retrieval.
        """
        if not text.strip():
            return []

        tokens = self.encoding.encode(text)
        chunks: list[Chunk] = []
        start = 0
        index = 0

        while start < len(tokens):
            end = min(start + self.chunk_size, len(tokens))
            chunk_tokens = tokens[start:end]
            chunk_text = self.encoding.decode(chunk_tokens)

            chunks.append(Chunk(
                index=index,
                content=chunk_text,
                token_count=len(chunk_tokens),
            ))

            if end == len(tokens):
                break

            start = end - self.overlap
            index += 1

        logger.info(f"Chunked text into {len(chunks)} chunks (size={self.chunk_size}, overlap={self.overlap})")
        return chunks
