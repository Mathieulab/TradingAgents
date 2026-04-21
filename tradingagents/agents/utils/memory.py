"""Financial situation memory using BM25 for lexical similarity matching.

Uses BM25 (Best Matching 25) algorithm for retrieval - no API calls,
no token limits, works offline with any LLM provider.
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from rank_bm25 import BM25Okapi
from typing import Dict, List, Optional, Set, Tuple
import re


class FinancialSituationMemory:
    """Memory system for storing and retrieving financial situations using BM25."""

    def __init__(self, name: str, config: dict = None):
        """Initialize the memory system.

        Args:
            name: Name identifier for this memory instance
            config: Configuration dict (kept for API compatibility, not used for BM25)
        """
        self.name = name
        self.config = config or {}
        self.storage_dir = self._resolve_storage_dir()
        self.storage_path = os.path.join(self.storage_dir, f"{self.name}.json")
        self.records: List[Dict[str, object]] = []
        self.documents: List[str] = []
        self.recommendations: List[str] = []
        self.bm25 = None
        self._fingerprints: Set[str] = set()
        os.makedirs(self.storage_dir, exist_ok=True)
        self._load()

    def _resolve_storage_dir(self) -> str:
        """Resolve the directory where memory files are persisted."""
        configured_dir = self.config.get("memory_dir")
        if configured_dir:
            return os.path.abspath(configured_dir)

        project_dir = self.config.get("project_dir") or os.getcwd()
        return os.path.join(os.path.abspath(project_dir), "memory")

    def _sync_indexes_from_records(self):
        """Rebuild in-memory lists used by BM25 retrieval."""
        self.documents = [str(record.get("situation", "")) for record in self.records]
        self.recommendations = [
            str(record.get("recommendation", "")) for record in self.records
        ]

    def _load(self):
        """Load persisted memory records from disk if available."""
        if not os.path.exists(self.storage_path):
            self._sync_indexes_from_records()
            self._rebuild_index()
            return

        try:
            with open(self.storage_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            payload = []

        if isinstance(payload, dict):
            payload = payload.get("records", [])

        if not isinstance(payload, list):
            payload = []

        self.records = []
        for record in payload:
            if not isinstance(record, dict):
                continue

            situation = str(record.get("situation", ""))
            recommendation = str(record.get("recommendation", ""))
            metadata = record.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}

            self.records.append(
                {
                    "situation": situation,
                    "recommendation": recommendation,
                    "metadata": metadata,
                    "created_at": record.get("created_at"),
                }
            )

        self._fingerprints = {self._fingerprint(r["situation"]) for r in self.records}
        self._sync_indexes_from_records()
        self._rebuild_index()

    def _persist(self):
        """Persist memory records to disk."""
        payload = {
            "name": self.name,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "records": self.records,
        }
        with open(self.storage_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=True)

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text for BM25 indexing.

        Simple whitespace + punctuation tokenization with lowercasing.
        """
        # Lowercase and split on non-alphanumeric characters
        tokens = re.findall(r'\b\w+\b', text.lower())
        return tokens

    def _fingerprint(self, situation: str) -> str:
        """SHA-256 fingerprint of the first 1 000 chars of a situation.

        Used to skip storing duplicate reflections for the same analysis run.
        """
        return hashlib.sha256(situation[:1000].encode("utf-8")).hexdigest()

    def _rebuild_index(self):
        """Rebuild the BM25 index after adding documents."""
        if self.documents:
            tokenized_docs = [self._tokenize(doc) for doc in self.documents]
            self.bm25 = BM25Okapi(tokenized_docs)
        else:
            self.bm25 = None

    def add_situations(
        self,
        situations_and_advice: List[Tuple[str, str]],
        metadata_list: Optional[List[Optional[Dict[str, object]]]] = None,
    ):
        """Add financial situations and their corresponding advice.

        Args:
            situations_and_advice: List of tuples (situation, recommendation)
            metadata_list: Optional list of metadata dictionaries aligned to the tuples
        """
        if metadata_list is None:
            metadata_list = [None] * len(situations_and_advice)

        if len(metadata_list) != len(situations_and_advice):
            raise ValueError("metadata_list must match situations_and_advice length")

        added = 0
        for (situation, recommendation), metadata in zip(
            situations_and_advice, metadata_list
        ):
            fp = self._fingerprint(situation)
            if fp in self._fingerprints:
                continue  # duplicate — already learned from this analysis run

            self._fingerprints.add(fp)
            self.records.append(
                {
                    "situation": situation,
                    "recommendation": recommendation,
                    "metadata": metadata or {},
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            added += 1

        if added:
            self._sync_indexes_from_records()
            self._rebuild_index()
            self._persist()

    def get_memories(self, current_situation: str, n_matches: int = 1) -> List[dict]:
        """Find matching recommendations using BM25 similarity.

        Args:
            current_situation: The current financial situation to match against
            n_matches: Number of top matches to return

        Returns:
            List of dicts with matched_situation, recommendation, and similarity_score
        """
        if not self.documents or self.bm25 is None:
            return []

        # Tokenize query
        query_tokens = self._tokenize(current_situation)

        # Get BM25 scores for all documents
        scores = self.bm25.get_scores(query_tokens)

        # Get top-n indices sorted by score (descending)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:n_matches]

        # Build results
        results = []
        max_score = max(scores) if max(scores) > 0 else 1  # Normalize scores

        for idx in top_indices:
            # Normalize score to 0-1 range for consistency
            normalized_score = scores[idx] / max_score if max_score > 0 else 0
            record = self.records[idx]
            results.append({
                "matched_situation": self.documents[idx],
                "recommendation": self.recommendations[idx],
                "similarity_score": normalized_score,
                "metadata": record.get("metadata", {}),
                "created_at": record.get("created_at"),
            })

        return results

    def get_performance_summary(self) -> Dict[str, object]:
        """Return aggregate correctness and return metrics for stored memories."""
        evaluated_records = []
        returns_values = []
        for record in self.records:
            metadata = record.get("metadata") or {}
            if "was_correct" in metadata:
                evaluated_records.append(bool(metadata["was_correct"]))
            returns_value = metadata.get("returns_losses")
            if isinstance(returns_value, (int, float)):
                returns_values.append(float(returns_value))

        total_records = len(self.records)
        evaluated_count = len(evaluated_records)
        correct_count = sum(1 for was_correct in evaluated_records if was_correct)
        incorrect_count = evaluated_count - correct_count
        success_rate = (
            round((correct_count / evaluated_count) * 100, 2)
            if evaluated_count
            else None
        )

        return {
            "name": self.name,
            "storage_path": self.storage_path,
            "total_records": total_records,
            "evaluated_records": evaluated_count,
            "correct_records": correct_count,
            "incorrect_records": incorrect_count,
            "success_rate": success_rate,
            "average_returns": round(sum(returns_values) / len(returns_values), 4)
            if returns_values
            else None,
        }

    def get_prompt_context(self, current_situation: str, n_matches: int = 2) -> str:
        """Build a concise prompt block with historical performance and similar lessons."""
        summary = self.get_performance_summary()
        summary_parts = [
            f"Total memories: {summary['total_records']}",
            f"Evaluated memories: {summary['evaluated_records']}",
        ]

        if summary["success_rate"] is not None:
            summary_parts.append(f"Historical success rate: {summary['success_rate']}%")
        if summary["average_returns"] is not None:
            summary_parts.append(f"Average returns: {summary['average_returns']}")

        memories = self.get_memories(current_situation, n_matches=n_matches)
        if not memories:
            return "Memory Performance: " + ", ".join(summary_parts) + "\nSimilar lessons: none yet."

        lesson_lines = []
        for index, memory in enumerate(memories, start=1):
            metadata = memory.get("metadata") or {}
            meta_parts = []
            if metadata.get("trade_date"):
                meta_parts.append(f"date={metadata['trade_date']}")
            if metadata.get("returns_losses") is not None:
                meta_parts.append(f"return={metadata['returns_losses']}")
            if metadata.get("was_correct") is not None:
                meta_parts.append(
                    "correct=yes" if metadata["was_correct"] else "correct=no"
                )
            if memory.get("similarity_score") is not None:
                meta_parts.append(
                    f"similarity={round(float(memory['similarity_score']) * 100, 1)}%"
                )

            meta_suffix = f" [{' | '.join(meta_parts)}]" if meta_parts else ""
            lesson_lines.append(
                f"{index}. {memory['recommendation']}{meta_suffix}"
            )

        return (
            "Memory Performance: "
            + ", ".join(summary_parts)
            + "\nSimilar lessons:\n"
            + "\n".join(lesson_lines)
        )

    def clear(self):
        """Clear all stored memories."""
        self.records = []
        self.documents = []
        self.recommendations = []
        self.bm25 = None
        self._fingerprints = set()
        self._persist()


if __name__ == "__main__":
    # Example usage
    matcher = FinancialSituationMemory("test_memory")

    # Example data
    example_data = [
        (
            "High inflation rate with rising interest rates and declining consumer spending",
            "Consider defensive sectors like consumer staples and utilities. Review fixed-income portfolio duration.",
        ),
        (
            "Tech sector showing high volatility with increasing institutional selling pressure",
            "Reduce exposure to high-growth tech stocks. Look for value opportunities in established tech companies with strong cash flows.",
        ),
        (
            "Strong dollar affecting emerging markets with increasing forex volatility",
            "Hedge currency exposure in international positions. Consider reducing allocation to emerging market debt.",
        ),
        (
            "Market showing signs of sector rotation with rising yields",
            "Rebalance portfolio to maintain target allocations. Consider increasing exposure to sectors benefiting from higher rates.",
        ),
    ]

    # Add the example situations and recommendations
    matcher.add_situations(example_data)

    # Example query
    current_situation = """
    Market showing increased volatility in tech sector, with institutional investors
    reducing positions and rising interest rates affecting growth stock valuations
    """

    try:
        recommendations = matcher.get_memories(current_situation, n_matches=2)

        for i, rec in enumerate(recommendations, 1):
            print(f"\nMatch {i}:")
            print(f"Similarity Score: {rec['similarity_score']:.2f}")
            print(f"Matched Situation: {rec['matched_situation']}")
            print(f"Recommendation: {rec['recommendation']}")

    except Exception as e:
        print(f"Error during recommendation: {str(e)}")
