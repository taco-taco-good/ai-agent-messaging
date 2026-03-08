from __future__ import annotations

import unittest

from agent_messaging.memory.metadata import MetadataGenerator


class MetadataGeneratorTests(unittest.TestCase):
    def test_generate_metadata_extracts_tags_topic_and_summary(self) -> None:
        generator = MetadataGenerator()
        metadata = generator.generate(
            user_text="Review the Discord session model and memory search behavior.",
            assistant_text="The session model is channel-based and memory search should stay in the runtime tool layer.",
        )
        self.assertTrue(metadata.topic)
        self.assertTrue(metadata.summary)
        self.assertTrue(metadata.tags)
