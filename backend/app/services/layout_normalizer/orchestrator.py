from __future__ import annotations

from app.domain.models import DocumentIR, DocumentIRBlock, DocumentProfile

from app.services.layout_normalizer.block_merging import (
    _is_screen_chrome,
    _layout_sort_key,
    _merge_same_line_blocks,
    _merge_wrapped_paragraph_blocks,
)
from app.services.layout_normalizer.classification import (
    LAYOUT_NORMALIZER_VERSION,
    _classify_blocks,
    _split_patient_header_block_ids,
)
from app.services.layout_normalizer.key_value_derivation import _derive_key_value_blocks
from app.services.layout_normalizer.sections import (
    _renumber_blocks,
    _sections_from_blocks,
)


def normalize_document_layout(document_ir: DocumentIR, profile: DocumentProfile) -> DocumentIR:
    config = profile.layout_normalization
    if not config.enabled:
        return document_ir

    kept: list[DocumentIRBlock] = []
    removed_count = 0
    for block in document_ir.blocks:
        if config.remove_screen_chrome and _is_screen_chrome(block.text, config):
            removed_count += 1
            continue
        kept.append(block)

    ordered = sorted(kept, key=_layout_sort_key)
    merged_blocks, merged_count = _merge_same_line_blocks(ordered, config) if config.merge_same_line_fragments else (ordered, 0)
    split_patient_header_ids = _split_patient_header_block_ids(merged_blocks, config)
    paragraph_blocks, paragraph_count = _merge_wrapped_paragraph_blocks(merged_blocks, config)
    normalized_blocks = _classify_blocks(paragraph_blocks, profile, config, split_patient_header_ids)
    if config.derive_key_value_blocks:
        output_blocks, derived_count, neighbor_derived_count = _derive_key_value_blocks(normalized_blocks, config)
    else:
        output_blocks = _renumber_blocks(normalized_blocks)
        derived_count = 0
        neighbor_derived_count = 0

    metadata = {
        **document_ir.metadata,
        "layout_normalization": {
            "version": LAYOUT_NORMALIZER_VERSION,
            "enabled": True,
            "input_blocks": len(document_ir.blocks),
            "output_blocks": len(output_blocks),
            "removed_screen_chrome_blocks": removed_count,
            "merged_same_line_fragments": merged_count,
            "merged_wrapped_paragraphs": paragraph_count,
            "derived_key_value_blocks": derived_count,
            "derived_neighbor_key_value_blocks": neighbor_derived_count,
        },
    }
    return document_ir.model_copy(
        update={
            "blocks": output_blocks,
            "sections": _sections_from_blocks(output_blocks),
            "metadata": metadata,
        }
    )
