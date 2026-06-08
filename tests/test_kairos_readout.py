from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from daedalus_wechat.cli import main
from daedalus_wechat.daemon import BridgeDaemon
from daedalus_wechat.kairos_readout import (
    format_kairos_intraday_alert,
    format_kairos_owner_brief,
    format_kairos_owner_brief_compact,
    format_kairos_owner_daily_archive_dates,
    format_kairos_today_readout,
    load_kairos_forward_shadow_track_record,
    load_kairos_hypothesis_scout_readout,
    load_kairos_intraday_alert,
    load_kairos_intraday_candidate_manifest,
    load_kairos_intraday_eod_outcome_review,
    load_kairos_intraday_eod_review_queue,
    load_kairos_owner_brief,
    load_kairos_owner_daily_archive,
    load_kairos_owner_daily_package,
    load_kairos_owner_review_truth_units,
    load_kairos_today_readout,
)


def _sample_payload() -> dict[str, object]:
    return {
        "run_status": "WARN",
        "owner_summary": {
            "advisory_ready": False,
            "authority_state": "report_only",
            "owner_action": "review framework blockers; no trading authority",
            "freshness_statement": "readout is generated from report-only builders",
            "blocked_sections": [],
            "warn_sections": ["canonical_surface", "source_bridge"],
            "no_trade_reasons": ["receipts missing"],
            "report_only_leads": ["canonical thin core exists"],
        },
        "authority": {
            "authority_delta": "none",
            "owner_advisory_allowed": False,
            "live_broker_allowed": False,
        },
    }


def _sample_owner_brief_payload() -> dict[str, object]:
    return {
        "status": "REPORT_ONLY_SHORT_CYCLE_OWNER_REVIEW_BRIEF",
        "as_of_date": "2026-06-05",
        "target_trade_date": "2026-06-08",
        "accepted_edges": 0,
        "market_facts": {
            "market_regime": "CHOPPY",
            "emotion_phase": "hot",
            "breadth_up_pct": 59.63,
            "limit_up_count": 88,
            "broken_limit_up_count": 63,
            "first_limit_up_count": 82,
            "highest_continuous_board": 5,
        },
        "industry_concentration": {
            "state": "HIGH_INDUSTRY_CONCENTRATION",
            "top_industry_share_pct": 51.16,
            "hhi": 0.3077,
            "top_industries": [
                {
                    "industry_name": "元器件",
                    "candidate_count": 22,
                    "candidate_share_pct": 51.16,
                }
            ],
        },
        "explosive_short_cycle_posture": {
            "posture_state": (
                "RIGHT_TAIL_TAPE_ACTIVE__MODERATE_SETUP_SUPPLY__"
                "HIGH_INDUSTRY_CONCENTRATION"
            ),
            "setup_supply": {
                "owner_candidate_count": 43,
                "stock_watchlist_count": 20,
                "limit_board_continuation_candidate_count": 12,
                "state": "MODERATE_SETUP_SUPPLY",
                "passive_timing_read": (
                    "setup supply is an observed market thermometer and research "
                    "input; it is not a position-sizing instruction"
                ),
            },
            "right_tail_tape": {
                "state": "RIGHT_TAIL_TAPE_ACTIVE",
                "limit_up_count": 88,
                "highest_continuous_board": 5,
                "broken_limit_up_count": 63,
            },
            "concentration": {
                "top_industry_share_pct": 51.16,
            },
        },
        "cross_horizon_right_tail_candidate_clusters": {
            "status": "REPORT_ONLY_CURRENT_CANDIDATE_CROSS_HORIZON_RIGHT_TAIL_INTERSECTION",
            "matched_cluster_count": 1,
            "matched_stock_candidate_count": 4,
            "consensus_hypothesis_count": 17,
            "top_clusters": [
                {
                    "candidate_count": 4,
                    "industry_name": "小金属",
                    "tactic_id": "prior_weak_close_reclaim_volume",
                    "consensus_snapshot": {
                        "evolution_next_action": (
                            "keep_or_prioritize_for_forward_shadow_observation"
                        ),
                        "min_right_tail_ready_window_count": 1,
                        "next_open_close_tail5_max_share_pct": 16.6667,
                        "next_open_following_close_tail5_max_share_pct": 21.9048,
                    },
                    "top_stocks": [
                        {"stock_name": "盛新锂能", "symbol": "002240.SZ"},
                        {"stock_name": "中矿资源", "symbol": "002738.SZ"},
                    ],
                }
            ],
        },
        "long_window_stability": {
            "machine_route_counts": {
                "STRICT_CANDIDATE_FORWARD_SHADOW_OBSERVATION": 9,
                "RIGHT_TAIL_FORWARD_SHADOW_OBSERVATION": 8,
                "PREDICATE_SUPPORT_ADAPTATION": 13,
            },
            "adapt_route_counts": {
                "RIGHT_TAIL_FORWARD_SHADOW_OBSERVATION": 8,
                "PREDICATE_SUPPORT_ADAPTATION": 13,
            },
            "top_keep_rows": [
                {
                    "hypothesis_id": "leader_orderly_flat_pullback",
                    "machine_route": "STRICT_CANDIDATE_FORWARD_SHADOW_OBSERVATION",
                    "candidate_window_count": 4,
                    "cross_horizon_ready_window_ids": [
                        "short_cycle_long_2023_h1",
                        "short_cycle_long_2023_h2",
                        "short_cycle_long_2024_h1",
                    ],
                    "next_open_following_close_best_net_excess_pct": 0.0739,
                    "next_open_following_close_right_tail_return_ge_5pct_max_share_pct": 20.0,
                    "windows_tested": 7,
                }
            ],
            "top_adapt_rows": [
                {
                    "hypothesis_id": "prior_limit_gap_down_reclaim",
                    "machine_route": "RIGHT_TAIL_FORWARD_SHADOW_OBSERVATION",
                    "adapt_route": "RIGHT_TAIL_FORWARD_SHADOW_OBSERVATION",
                    "candidate_window_count": 0,
                    "cross_horizon_ready_window_ids": [
                        "short_cycle_long_2025_h2",
                        "short_cycle_long_2026_q1_q2",
                    ],
                    "next_open_following_close_best_net_excess_pct": 1.7168,
                    "next_open_following_close_right_tail_return_ge_5pct_max_share_pct": 40.0,
                    "windows_tested": 7,
                },
                {
                    "hypothesis_id": "cold_world_volume_exhaustion",
                    "machine_route": "PREDICATE_SUPPORT_ADAPTATION",
                    "adapt_route": "PREDICATE_SUPPORT_ADAPTATION",
                    "candidate_window_count": 0,
                    "cross_horizon_ready_window_ids": [],
                    "next_open_following_close_best_net_excess_pct": None,
                    "next_open_following_close_right_tail_return_ge_5pct_max_share_pct": None,
                    "windows_tested": 7,
                },
            ],
            "cross_horizon_right_tail_consensus": {
                "status": "REPORT_ONLY_CROSS_HORIZON_RIGHT_TAIL_CONSENSUS",
                "hypothesis_count": 17,
                "multi_window_min_ready_threshold": 2,
                "both_horizon_multi_window_ready_hypothesis_count": 0,
                "both_horizon_single_window_only_hypothesis_count": 17,
                "support_state": "CROSS_HORIZON_SINGLE_WINDOW_ONLY",
                "support_warning": (
                    "cross-horizon right-tail rows with single-window support are "
                    "directional review units only, not cross-era stability evidence"
                ),
                "support_width_backlog": {
                    "status": "REPORT_ONLY_CROSS_HORIZON_SUPPORT_WIDTH_BACKLOG",
                    "route": "EXPAND_WINDOW_SUPPORT_BEFORE_STABILITY_CLAIM",
                    "candidate_count": 17,
                    "min_ready_threshold": 2,
                },
                "top_rows": [
                    {
                        "hypothesis_id": "prior_limit_gap_hold",
                        "min_right_tail_ready_window_count": 2,
                        "next_open_close_best_net_excess_pct": 0.6821,
                        "next_open_close_tail5_max_share_pct": 35.2941,
                        "next_open_following_close_best_net_excess_pct": 2.9334,
                        "next_open_following_close_tail5_max_share_pct": 38.8889,
                        "windows_tested": 7,
                        "evolution_next_action": (
                            "adapt_predicate_or_surface_coverage_before_rerun"
                        ),
                    },
                    {
                        "hypothesis_id": "deep_shakeout_power_recover",
                        "min_right_tail_ready_window_count": 7,
                        "next_open_close_best_net_excess_pct": 0.6658,
                        "next_open_close_tail5_max_share_pct": 26.6667,
                        "next_open_following_close_best_net_excess_pct": 0.6206,
                        "next_open_following_close_tail5_max_share_pct": 30.2326,
                        "windows_tested": 7,
                        "evolution_next_action": (
                            "keep_or_prioritize_for_forward_shadow_observation"
                        ),
                    },
                ],
            },
        },
        "owner_review_candidates": [
            {
                "review_rank": 1,
                "symbol": "002251.SZ",
                "stock_name": "步步高",
                "industry_name": "超市连锁",
                "tactic_name": "高开后前30分钟承接",
                "strategy_metadata_zh": {
                    "name_zh": "高开后前30分钟承接",
                    "pattern_zh": "高开后没有快速转弱, 前30分钟仍有承接。",
                    "selection_policy_zh": "优先看强势股池、流动性可交易、非一字涨停不可买行。",
                    "world_state_zh": "更适合右尾活跃、涨停生态不弱、候选供给扩张的短周期环境。",
                    "execution_template_zh": "次日开盘后观察前30分钟, 只做观察触发, 不是买入指令。",
                },
                "owner_confidence_label": "可用参考",
                "evidence_wounds": ["not_industry_neutral_contains_sector_beta"],
                "tactic_support": {
                    "baseline_claim_boundary": (
                        "cached-retry tactic excess is measured against same-date "
                        "level-2 industry baseline; candidate rank itself remains "
                        "a non-industry-neutral watchlist heuristic"
                    ),
                    "baseline_scope": "same_date_same_level_2_industry_executable_baseline",
                    "cost_total_pct": 0.272,
                    "date_block_ci_lower_pct": -0.5222,
                    "date_block_ci_upper_pct": 1.6045,
                    "gross_excess_pct": 1.2576,
                    "net_excess_pct": 0.9856,
                    "next_open_close_net_excess_pct": -0.0461,
                    "next_open_close_right_tail_return_ge_5pct_share_pct": 15.0757,
                    "next_open_following_close_net_excess_pct": 0.1271,
                    "next_open_following_close_right_tail_return_ge_5pct_share_pct": 25.1481,
                    "right_tail_return_ge_5pct_share_pct": 43.9801,
                    "right_tail_return_p90_pct": 19.4347,
                    "row_n": 1005,
                    "date_block_effective_n": 32,
                },
            }
        ],
        "weak_signal_review_queue": [
            {
                "hypothesis_id": "high_gap_first30m_hold",
                "window_id": "short_cycle_predicate_2026_q2",
                "horizon_id": "next_open_to_d5_close",
                "route": "NEEDS_FORWARD_SHADOW",
                "gross_excess_pct": 1.2576,
                "net_excess_pct": 0.9856,
                "win_rate_pct": 48.36,
                "row_n": 1005,
                "date_block_effective_n": 32,
                "next_action": (
                    "freeze into forward-shadow and observe before owner ranking claim"
                ),
                "wounds": [
                    "static_cost_stamp_not_fill_simulator",
                    "needs_date_block_ci",
                    "needs_fdr_holdout_or_forward_shadow_before_edge_claim",
                ],
            }
        ],
        "environment_diagnostics": {
            "case_count": 24,
            "current_for_package_as_of": True,
            "freshness_status": "STALE_FOR_PACKAGE_AS_OF",
            "current_promising_count": 0,
            "diagnostic_promising_count": 6,
            "rigor_summary": {
                "case_wound_count": 4,
                "date_block_ci_crosses_zero_count": 3,
                "date_block_ci_non_cross_zero_count": 2,
                "fdr_known_count": 6,
                "fdr_pass_count": 2,
                "posthoc_variant_selection_count": 6,
                "review_unit_count": 6,
            },
        },
        "limit_board_base_rates": [
            {
                "context_state": "sealed_after_break",
                "event_n": 7134,
                "date_count": 811,
                "next_open_to_close_pct": 0.82,
            }
        ],
    }


def _sample_owner_daily_package_payload() -> dict[str, object]:
    return {
        "status": "REPORT_ONLY_SHORT_CYCLE_OWNER_DAILY_PACKAGE",
        "as_of_date": "2026-06-05",
        "target_trade_date": "2026-06-08",
        "accepted_edges": 0,
        "environment_conditioned_ab_sweep": {
            "summary": {
                "freshness_status": "CURRENT_FOR_PACKAGE_AS_OF",
                "promising_count": 10,
                "diagnostic_promising_count": 10,
                "route_counts": {
                    "PROMISING_REVIEW_ONLY": 10,
                    "PLACEBO_CONTROL_WEAK": 11,
                    "NOT_BETTER_THAN_POOLED": 3,
                },
            },
            "diagnostic_wounds": {
                "candidate_variants_selected_posthoc": True,
                "trial_denominator_case_count": 24,
                "uses_environment_fingerprint_trust_gate": True,
                "fdr_pass_count": 2,
                "fdr_tested_case_count": 24,
                "fdr_q": 0.05,
                "fdr_procedure": "benjamini_hochberg_on_placebo_rank_rates",
                "date_block_ci_ready_count": 24,
                "date_block_ci_crosses_zero_count": 24,
                "date_block_ci_low_date_support_count": 0,
                "date_block_ci_method": (
                    "deterministic_signal_date_block_bootstrap_v1_on_ab_per_date_excess"
                ),
                "trusted_axis_count": 4,
                "similarity_feature_count": 4,
                "blocked_axes_not_used": [
                    "world_*_WARN_REVIEW_BEFORE_WEIGHTING",
                    "product_market_temperature",
                    "product_rotation_speed",
                ],
                "route_counts": {
                    "PROMISING_REVIEW_ONLY": 10,
                    "PLACEBO_CONTROL_WEAK": 11,
                    "NOT_BETTER_THAN_POOLED": 3,
                },
            },
        },
        "long_window_cached_retry_sweep": {
            "next_open_following_close_diagnostic_summary": {
                "status": "REPORT_ONLY_NEXT_OPEN_FOLLOWING_CLOSE_LONG_WINDOW_DIAGNOSTIC",
                "horizon_id": "next_open_to_following_close",
                "hypothesis_count": 30,
                "positive_net_hypothesis_count": 8,
                "positive_net_window_count": 8,
                "cost_killed_hypothesis_count": 16,
                "right_tail_ready_hypothesis_count": 17,
                "top_positive_net_rows": [
                    {
                        "hypothesis_id": "prior_limit_orderly_digest",
                        "best_net_excess_pct": 0.8816,
                        "right_tail_return_ge_5pct_max_share_pct": 25.9259,
                        "right_tail_return_p90_max_pct": 9.1973,
                        "windows_tested": 7,
                        "evolution_next_action": (
                            "adapt_predicate_or_surface_coverage_before_rerun"
                        ),
                    }
                ],
            }
        },
        "forward_shadow_track_record": {
            "source_status": "PENDING_SHORT_CYCLE_FORWARD_SHADOW_TRACK_RECORD",
            "freeze_id": "short_cycle_trigger_forward_shadow_20260608_asof_20260605",
            "candidate_track_count": 244,
            "trigger_fired_count": 0,
            "pending_trigger_count": 244,
            "following_observed_count": 0,
            "following_scoreable_candidate_count": 0,
            "d3_observed_count": 0,
            "d5_observed_count": 0,
            "scoreable_candidate_count": 0,
            "lifecycle_state": "PENDING_TARGET_OPEN_STATE",
            "next_action": "wait for target open-state and first30m fields",
        },
        "owner_review_brief": {
            "source_status": "REPORT_ONLY_SHORT_CYCLE_OWNER_REVIEW_BRIEF",
            "owner_review_candidate_count": 40,
            "source_markdown_path": "/tmp/short_cycle_owner_review_brief_latest.md",
        },
        "intraday_candidate_manifest": {
            "source_status": "REPORT_ONLY_SHORT_CYCLE_INTRADAY_CANDIDATE_MANIFEST",
            "candidate_count": 144,
            "unique_symbol_count": 41,
            "collection_window_count": 3,
            "source_markdown_path": "/tmp/short_cycle_intraday_candidate_manifest_latest.md",
            "edge_collection_contract": {
                "edge_runtime": "Windows ft-edge",
                "transport": "file handoff; no DB writes",
            },
            "collection_windows": [
                {
                    "time_cst": "09:26",
                    "window_id": "opening_print_0926",
                    "owner_use": "opening print observation",
                },
                {
                    "time_cst": "09:36",
                    "window_id": "first5m_preliminary_0936",
                    "owner_use": "first five minute observation",
                },
            ],
        },
    }


def _sample_forward_shadow_track_record_payload() -> dict[str, object]:
    return {
        "contract": "ftkairos.research_substrate.short_cycle_forward_shadow_track_record",
        "status": "PENDING_SHORT_CYCLE_FORWARD_SHADOW_TRACK_RECORD",
        "as_of_date": "2026-06-05",
        "target_trade_date": "2026-06-08",
        "accepted_edges": 0,
        "freeze_id": "short_cycle_trigger_forward_shadow_20260608_asof_20260605",
        "observed_from": {
            "open_state_waterline": "2026-06-05",
        },
        "summary": {
            "candidate_track_count": 244,
            "evidence_track_count": 204,
            "trigger_fired_count": 0,
            "trigger_not_fired_count": 0,
            "pending_trigger_count": 244,
            "following_observed_count": 0,
            "following_scoreable_candidate_count": 0,
            "d3_observed_count": 0,
            "d5_observed_count": 0,
            "scoreable_candidate_count": 0,
            "lifecycle_state": "PENDING_TARGET_OPEN_STATE",
            "next_action": "wait for target open-state and first30m fields",
            "next_observation_targets": [
                {
                    "target": "target_open_state",
                    "date": "2026-06-08",
                    "reason": "PENDING_TARGET_OPEN_STATE",
                    "candidate_count": 244,
                }
            ],
        },
    }


def _sample_hypothesis_scout_readout_payload() -> dict[str, object]:
    return {
        "status": "REPORT_ONLY_SHORT_CYCLE_HYPOTHESIS_SCOUT_READOUT",
        "accepted_edges": 0,
        "report_path": "/tmp/short_cycle_hypothesis_scout_readout_latest.json",
        "markdown_path": "/tmp/short_cycle_hypothesis_scout_readout_latest.md",
        "counts": {
            "scout_cell_count": 724,
            "hypothesis_card_count": 40,
            "dispatchable_pending_run_cell_count": 192,
            "daywalk_report_materialized_cell_count": 328,
            "specialized_readout_ready_cell_count": 124,
            "needs_executable_spec_cell_count": 0,
            "pending_surface_cell_count": 80,
        },
        "owner_review_surface": {
            "surface_status": "REPORT_ONLY_SCOUT_INTAKE_DENOMINATOR",
            "top_families": [
                {
                    "name": "execution_template_ablation",
                    "family_name_zh": "执行模板对照",
                    "condition_summary_zh": "比较次日开盘、前5分钟VWAP、尾盘买和持有期差异。",
                    "count": 92,
                },
                {
                    "name": "intraday_price_volume",
                    "family_name_zh": "盘中量价",
                    "condition_summary_zh": "观察尾盘吸筹、前30分钟突破、放量突破和VWAP修复。",
                    "count": 88,
                },
                {
                    "name": "auction_microstructure",
                    "family_name_zh": "集合竞价微结构",
                    "condition_summary_zh": "观察竞价量价承接、高开失败、低开修复和前30分钟确认。",
                    "count": 80,
                },
            ],
            "top_hypotheses": [
                {
                    "name": "next_open_vs_first5m_vwap_gap",
                    "hypothesis_name_zh": "次日开盘对前5分钟VWAP",
                    "count": 32,
                },
                {
                    "name": "tail_accumulation_next_open",
                    "hypothesis_name_zh": "尾盘吸筹次日开盘",
                    "count": 32,
                },
            ],
            "dispatchable_examples": [
                {
                    "hypothesis_id": "ice_point_repair_first_board",
                    "family": "emotion_cycle_timing",
                    "horizon_id": "next_open_to_d3_close",
                    "route": "NEEDS_DAYWALK",
                    "execution_dispatch": "EXECUTABLE",
                    "missing_surface_requirements": [],
                    "next_action": "run_daywalk_stability_and_forward_observed_readout",
                    "owner_visible_metadata_zh": {
                        "hypothesis_name_zh": "冰点修复首板",
                        "family_name_zh": "情绪周期择时",
                        "condition_summary_zh": "观察冰点、退潮、高潮分歧和修复日。",
                    },
                }
            ],
            "already_materialized_daywalk_examples": [
                {
                    "hypothesis_id": "ice_point_repair_first_board",
                    "family": "emotion_cycle_timing",
                    "horizon_id": "next_open_to_d3_close",
                    "route": "NEEDS_DAYWALK",
                    "execution_dispatch": "EXECUTABLE",
                    "missing_surface_requirements": [],
                    "existing_daywalk_report_paths": [
                        "/tmp/short_cycle_hypothesis_daywalk_ice_point_repair_first_board_long_latest.json"
                    ],
                    "next_action": "run_daywalk_stability_and_forward_observed_readout",
                    "owner_visible_metadata_zh": {
                        "hypothesis_name_zh": "冰点修复首板",
                        "family_name_zh": "情绪周期择时",
                        "condition_summary_zh": "观察冰点、退潮、高潮分歧和修复日。",
                    },
                }
            ],
            "needs_executable_spec_examples": [],
            "materialized_daywalk_outcome_summary": {
                "status": "REPORT_ONLY_OWNER_REVIEW_TRUTH_UNITS_SUMMARY",
                "truth_unit_count": 304,
                "route_counts": {
                    "strict_candidate_review_only": 35,
                    "owner_review_tail_watch": 26,
                    "needs_support_before_review": 120,
                    "observation_only_net_cost_missing": 69,
                    "observation_only_net_cost_killed": 5,
                    "right_tail_but_mean_negative_review_only": 49,
                },
                "confidence_counts": {
                    "usable_reference_net_ci_positive": 3,
                    "owner_tail_watch_support_ok": 78,
                    "thin_sample_only": 120,
                },
                "accepted_edges": 0,
                "report_only": True,
            },
            "pending_surface_examples": [
                {
                    "hypothesis_id": "northbound_out_active_money_smallcap",
                    "family": "fund_preference_flow",
                    "horizon_id": "next_open_to_d3_close",
                    "route": "RESOLVE_BLOCKER",
                    "execution_dispatch": None,
                    "missing_surface_requirements": ["canonical.northbound_flow_day"],
                    "next_action": "materialize_pit_safe_source_surface_before_freeze",
                    "owner_visible_metadata_zh": {
                        "hypothesis_name_zh": "北向弱但活跃资金小盘",
                        "family_name_zh": "资金偏好流",
                        "condition_summary_zh": "观察北向、龙虎榜、净流和机构偏好等资金足迹。",
                    },
                }
            ],
        },
    }


def _sample_owner_review_truth_units_payload() -> dict[str, object]:
    return {
        "status": "REPORT_ONLY_OWNER_REVIEW_TRUTH_UNITS_FROM_CACHED_RETRY",
        "schema_note": "variant-aware test fixture",
        "accepted_edges": 0,
        "truth_unit_count": 120,
        "variant_truth_unit_count": 2640,
        "source_result_count": 18480,
        "report_path": "/tmp/short_cycle_owner_review_truth_units_latest.json",
        "route_counts": {
            "strict_candidate_review_only": 9,
            "owner_review_tail_watch": 23,
            "right_tail_but_mean_negative_review_only": 29,
            "needs_support_before_review": 56,
        },
        "confidence_counts": {
            "usable_reference_net_ci_positive": 3,
            "owner_tail_watch_support_ok": 27,
            "observation_sample_ok_not_confirmed": 34,
        },
        "coverage_summary": {
            "observed_window_count": 7,
            "observed_windows": [
                "short_cycle_long_2023_h1",
                "short_cycle_long_2023_h2",
                "short_cycle_long_2024_h1",
                "short_cycle_long_2024_h2",
                "short_cycle_long_2025_h1",
                "short_cycle_long_2025_h2",
                "short_cycle_long_2026_q1_q2",
            ],
            "horizon_count": 3,
            "horizons": [
                "next_open_to_d3_close",
                "next_open_to_d5_close",
                "next_open_to_next_close",
            ],
            "multi_window_truth_unit_count": 64,
        },
        "top_truth_units": [
            {
                "hypothesis_id": "high_gap_first30m_hold",
                "horizon_id": "next_open_to_d5_close",
                "owner_review_route": "strict_candidate_review_only",
                "latest_verdict": "CANDIDATE_ONLY",
                "latest_executable_excess_pct_net_static_cost": 0.4774,
                "latest_right_tail_return_ge_5pct_share_pct": 34.1672,
                "latest_right_tail_return_p90_pct": 16.6771,
                "latest_executable_row_n": 4437,
                "latest_date_cluster_n": 86,
                "observed_window_count": 7,
                "latest_date_block_ci_crosses_zero": False,
            }
        ],
        "all_truth_units": [
            {
                "hypothesis_id": "high_gap_first30m_hold",
                "horizon_id": "next_open_to_d5_close",
                "source_type": "cached_retry",
                "owner_review_route": "strict_candidate_review_only",
                "latest_verdict": "CANDIDATE_ONLY",
                "latest_executable_excess_pct_gross": 0.75,
                "latest_executable_row_n": 4437,
                "latest_date_cluster_n": 86,
                "presentation_wounds": [],
            },
            {
                "hypothesis_id": "retreat_remnant_strength",
                "family": "sector_theme_lifecycle",
                "horizon_id": "next_open_to_d5_close",
                "source_type": "block_condition_daywalk",
                "owner_review_route": "strict_candidate_review_only",
                "latest_verdict": "CANDIDATE_ONLY",
                "latest_executable_excess_pct_gross": 0.5178,
                "latest_executable_row_n": 36575,
                "latest_date_cluster_n": 93,
                "presentation_wounds": [
                    "block_condition_daywalk_source_not_cached_retry",
                    "net_static_cost_not_available_for_source",
                    "date_block_ci_not_available_for_source",
                ],
            },
            {
                "hypothesis_id": "open_auction_volume_price_acceptance",
                "family": "auction_microstructure",
                "horizon_id": "next_open_to_d5_close",
                "source_type": "hypothesis_daywalk",
                "owner_review_route": "strict_candidate_review_only",
                "latest_verdict": "CANDIDATE_ONLY",
                "latest_executable_excess_pct_gross": 0.5727,
                "latest_executable_row_n": 1885,
                "latest_date_cluster_n": 91,
                "presentation_wounds": [
                    "hypothesis_daywalk_source_not_cached_retry",
                    "net_static_cost_not_available_for_source",
                    "date_block_ci_not_available_for_source",
                ],
            },
        ],
    }


def _sample_intraday_alert_payload() -> dict[str, object]:
    return {
        "status": "REPORT_ONLY_SHORT_CYCLE_INTRADAY_OWNER_ALERT",
        "as_of_date": "2026-06-05",
        "target_trade_date": "2026-06-08",
        "accepted_edges": 0,
        "candidate_count": 2,
        "markdown_path": "/tmp/short_cycle_intraday_owner_alert_latest.md",
        "realtime_snapshot_status": {
            "status": "PENDING_REALTIME_SNAPSHOT",
            "message": "no realtime snapshot supplied",
            "row_count": 0,
        },
        "observation_projection_status": {
            "candidate_source_counts": {
                "topn_owner_review": 20,
                "cross_horizon_right_tail_supplement": 7,
            },
            "observed_candidate_count": 2,
            "pending_candidate_count": 25,
            "cross_horizon_right_tail_cluster_count": 2,
            "cross_horizon_right_tail_cluster_candidate_count": 7,
        },
        "trigger_field_readiness_status": {
            "status": "TRIGGER_FIELDS_PENDING",
            "resolved_count": 2,
            "pending_count": 25,
            "pending_window_ids": [
                "first5m_preliminary_0936",
                "first30m_confirmation_1001",
            ],
        },
        "market_facts": {
            "market_regime": "CHOPPY",
            "emotion_phase": "hot",
            "limit_up_count": 88,
            "broken_limit_up_count": 63,
            "highest_continuous_board": 5,
        },
        "industry_concentration": {
            "state": "HIGH_INDUSTRY_CONCENTRATION",
            "top_industry_share_pct": 51.16,
        },
        "setup_supply": {
            "state": "MODERATE_SETUP_SUPPLY",
            "stock_watchlist_count": 20,
            "sealed_no_break_watchlist_count": 12,
        },
        "session_windows": [
            {
                "time_cst": "09:26",
                "window_id": "opening_print_0926",
                "owner_use": "read opening print",
                "trust_level": "high_if_snapshot_fresh",
            }
        ],
        "candidate_alerts": [
            {
                "rank": 1,
                "intraday_alert_source": "topn_owner_review",
                "symbol": "002251.SZ",
                "stock_name": "步步高",
                "industry_name": "超市连锁",
                "tactic_id": "high_gap_first30m_hold",
                "owner_confidence_label": "可用参考",
                "evidence_wounds": ["row_level_fdr_holdout_not_available"],
                "support_snapshot": {
                    "net_excess_pct": 0.9856,
                    "right_tail_return_ge_5pct_share_pct": 43.98,
                },
                "runtime_checkpoints": [
                    {
                        "window_id": "opening_print_0926",
                        "trigger_status": "PENDING_REALTIME_SNAPSHOT",
                    },
                    {
                        "window_id": "first5m_preliminary_0936",
                        "trigger_status": "PENDING_REALTIME_SNAPSHOT",
                    },
                    {
                        "window_id": "first30m_confirmation_1001",
                        "trigger_status": "PENDING_REALTIME_SNAPSHOT",
                    },
                ],
            },
            {
                "rank": 21,
                "intraday_alert_source": "cross_horizon_right_tail_supplement",
                "cross_horizon_right_tail_cluster": {
                    "cluster_key": "prior_weak_close_reclaim_volume::小金属",
                },
                "symbol": "002240.SZ",
                "stock_name": "盛新锂能",
                "industry_name": "小金属",
                "tactic_id": "prior_weak_close_reclaim_volume",
                "owner_confidence_label": "观察中",
                "evidence_wounds": [
                    "row_level_fdr_holdout_not_available",
                    "cluster_is_correlated_setup_not_independent_edge",
                ],
                "support_snapshot": {
                    "net_excess_pct": 1.6,
                    "right_tail_return_ge_5pct_share_pct": 30.22,
                },
                "runtime_checkpoints": [],
            }
        ],
    }


def _sample_intraday_alert_payload_with_triggered_row() -> dict[str, object]:
    payload = _sample_intraday_alert_payload()
    payload["trigger_field_readiness_status"] = {
        "status": "TRIGGER_FIELDS_READY",
        "resolved_count": 3,
        "pending_count": 0,
        "pending_window_ids": [],
    }
    candidate = payload["candidate_alerts"][0]  # type: ignore[index]
    candidate["runtime_checkpoints"] = [  # type: ignore[index]
        {
            "window_id": "opening_print_0926",
            "triggered": True,
            "trigger_status": "OPENING_GAP_TRIGGER_OBSERVED",
            "gap_pct": 0.0592,
        },
        {
            "window_id": "first5m_preliminary_0936",
            "triggered": True,
            "trigger_status": "FIRST5M_PRELIMINARY_ACCEPTANCE_OBSERVED",
            "first5m_return_pct": 0.0267,
        },
        {
            "window_id": "first30m_confirmation_1001",
            "triggered": True,
            "trigger_status": "FIRST30M_PATTERN_CONFIRMATION_OBSERVED",
            "first30m_return_pct": 0.0381,
            "drawdown_30m_from_open": -0.0068,
        },
    ]
    return payload


def _sample_future_blocked_intraday_alert_payload() -> dict[str, object]:
    payload = _sample_intraday_alert_payload()
    payload.update(
        {
            "status": "BLOCKED_SHORT_CYCLE_INTRADAY_OWNER_ALERT",
            "generated_at_utc": "2026-06-07T21:17:39Z",
            "errors": ["realtime_snapshot_future_timestamp"],
            "realtime_snapshot_status": {
                "status": "BLOCKED_SNAPSHOT_FUTURE_TIMESTAMP",
                "message": (
                    "realtime snapshot carries a future observation timestamp"
                ),
                "row_count": 28,
                "snapshot_time": "2026-06-08T09:26:05+08:00",
                "generated_at_utc": "2026-06-07T21:17:39Z",
                "max_observation_time_utc": "2026-06-08T01:26:05+00:00",
            },
            "observation_projection_status": {
                "candidate_source_counts": {
                    "topn_owner_review": 20,
                    "cross_horizon_right_tail_supplement": 8,
                },
                "observed_candidate_count": 0,
                "pending_candidate_count": 28,
                "cross_horizon_right_tail_cluster_count": 2,
                "cross_horizon_right_tail_cluster_candidate_count": 8,
            },
        }
    )
    return payload


def _sample_intraday_manifest_payload() -> dict[str, object]:
    return {
        "status": "REPORT_ONLY_SHORT_CYCLE_INTRADAY_CANDIDATE_MANIFEST",
        "as_of_date": "2026-06-05",
        "target_trade_date": "2026-06-08",
        "accepted_edges": 0,
        "candidate_count": 144,
        "unique_symbol_count": 41,
        "markdown_path": "/tmp/short_cycle_intraday_candidate_manifest_latest.md",
        "edge_collection_contract": {
            "edge_runtime": "Windows ft-edge",
            "transport": "file handoff; no DB writes",
        },
        "collection_windows": [
            {
                "time_cst": "09:26",
                "window_id": "opening_print_0926",
                "owner_use": "opening print observation",
            },
            {
                "time_cst": "09:36",
                "window_id": "first5m_preliminary_0936",
                "owner_use": "first five minute observation",
            },
            {
                "time_cst": "10:01",
                "window_id": "first30m_confirmation_1001",
                "owner_use": "first thirty minute observation",
            },
        ],
    }


def _sample_intraday_eod_review_queue_payload() -> dict[str, object]:
    return {
        "status": "PENDING_EOD_INTRADAY_REPLAY_REVIEW",
        "target_trade_date": "2026-06-08",
        "accepted_edges": 0,
        "candidate_review_unit_count": 20,
        "event_count": 14,
        "current_triggered_event_count": 2,
        "no_longer_triggered_event_count": 0,
        "candidate_review_unit_summary": {
            "by_state": {
                "CURRENT_TRIGGERED_DENOMINATOR_UNIT": 1,
                "PENDING_TRIGGER_FIELDS_DENOMINATOR_UNIT": 19,
            },
            "candidate_review_unit_count": 20,
            "current_triggered_candidate_count": 1,
            "ever_triggered_candidate_count": 1,
            "never_triggered_candidate_count": 19,
            "pending_or_missing_candidate_count": 19,
        },
        "intraday_universe_observation_scope": {
            "status": "UNIVERSE_INTRADAY_OBSERVATION_READY",
            "missing_intraday_universe_surfaces": [
                "industry_rotation_intraday",
                "money_effect_state_intraday",
                "all_system_signal_state_intraday",
            ],
            "universe_summary": {
                "row_count": 5208,
                "advancer_count": 699,
                "decliner_count": 4470,
                "up_2pct_count": 345,
                "down_2pct_count": 3120,
                "candidate_observed_in_universe_count": 39,
                "candidate_symbol_count": 41,
            },
        },
        "replay_archive_path": "/tmp/short_cycle_intraday_owner_alert_replay_2026-06-08.jsonl",
    }


def _sample_intraday_eod_outcome_review_payload(
    *,
    status: str = "REPORT_ONLY_INTRADAY_EOD_OUTCOME_REVIEW_READY",
) -> dict[str, object]:
    blocker = None
    matched_count = 2
    if status != "REPORT_ONLY_INTRADAY_EOD_OUTCOME_REVIEW_READY":
        matched_count = 0
        blocker = {
            "blocker_id": "target_trade_date_outcome_rows_not_matured",
            "target_trade_date": "2026-06-08",
            "next_action": "rerun forward outcome panel after target-day bars mature",
        }
    return {
        "contract": "ftkairos.research_substrate.short_cycle_intraday_eod_outcome_review",
        "status": status,
        "target_trade_date": "2026-06-08",
        "accepted_edges": 0,
        "report_only": True,
        "summary": {
            "candidate_review_unit_count": 20,
            "matched_panel_row_count": matched_count,
            "missing_panel_row_count": 20 - matched_count,
            "current_triggered_unit_count": 1,
            "ever_triggered_unit_count": 1,
            "never_triggered_unit_count": 1,
            "pending_or_missing_trigger_field_unit_count": 18,
            "can_compare_triggered_vs_denominator": matched_count == 2,
        },
        "blocker": blocker,
        "group_horizon_stats": {
            "current_triggered": {
                "matched_panel_row_count": 1,
                "horizons": [
                    {
                        "horizon_id": "next_open_to_following_close",
                        "mean_net_static_cost_return_pct": 7.7,
                        "positive_share_pct": 100.0,
                    }
                ],
            },
            "never_triggered": {
                "matched_panel_row_count": 1,
                "horizons": [
                    {
                        "horizon_id": "next_open_to_following_close",
                        "mean_net_static_cost_return_pct": -2.3,
                        "positive_share_pct": 0.0,
                    }
                ],
            },
            "all_candidates": {
                "matched_panel_row_count": 2,
                "horizons": [
                    {
                        "horizon_id": "next_open_to_following_close",
                        "mean_net_static_cost_return_pct": 2.7,
                        "positive_share_pct": 50.0,
                    }
                ],
            },
        },
    }


def test_load_kairos_today_readout_reads_report(tmp_path: Path) -> None:
    report_path = tmp_path / "owner_readiness_readout_latest.json"
    report_path.write_text(
        json.dumps(_sample_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    payload = load_kairos_today_readout(report_path)

    assert payload["run_status"] == "WARN"
    assert payload["report_path"] == str(report_path)
    assert payload["owner_summary"]["authority_state"] == "report_only"


def test_load_kairos_today_readout_missing_report_fails_closed(tmp_path: Path) -> None:
    report_path = tmp_path / "missing.json"

    payload = load_kairos_today_readout(report_path)

    assert payload["run_status"] == "MISSING"
    assert payload["owner_summary"]["advisory_ready"] is False
    assert payload["authority"]["authority_delta"] == "none"
    assert "owner_readiness_report" in payload["owner_summary"]["blocked_sections"]


def test_format_kairos_today_readout_keeps_report_only_boundary(tmp_path: Path) -> None:
    report_path = tmp_path / "owner_readiness_readout_latest.json"
    payload = _sample_payload()
    payload["report_path"] = str(report_path)

    text = format_kairos_today_readout(payload)

    assert "Kairos readiness=WARN" in text
    assert "authority_state=report_only" in text
    assert "advisory_ready=false" in text
    assert "boundary=read-only report; not an advisory packet" in text


def test_cli_kairos_today_does_not_require_bridge_state(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    report_path = tmp_path / "owner_readiness_readout_latest.json"
    report_path.write_text(
        json.dumps(_sample_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["daedalus-wechat", "kairos-today", "--report-path", str(report_path)],
    )

    rc = main()

    assert rc == 0
    out = capsys.readouterr().out
    assert "Kairos readiness=WARN" in out
    assert "boundary=read-only report; not an advisory packet" in out


def test_daemon_kairos_today_command_is_read_only() -> None:
    with patch(
        "daedalus_wechat.daemon.load_kairos_today_readout",
        return_value=_sample_payload(),
    ):
        text = BridgeDaemon._handle_command(BridgeDaemon.__new__(BridgeDaemon), "/kairos-today")

    assert "Kairos readiness=WARN" in text
    assert "advisory_ready=false" in text


def test_load_kairos_owner_brief_reads_latest_report(tmp_path: Path) -> None:
    report_path = tmp_path / "short_cycle_owner_review_brief_latest.json"
    report_path.write_text(
        json.dumps(_sample_owner_brief_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    payload = load_kairos_owner_brief(report_path)

    assert payload["status"] == "REPORT_ONLY_SHORT_CYCLE_OWNER_REVIEW_BRIEF"
    assert payload["report_path"] == str(report_path)
    assert payload["accepted_edges"] == 0


def test_load_kairos_owner_daily_package_reads_latest_report(tmp_path: Path) -> None:
    report_path = tmp_path / "short_cycle_owner_daily_package_latest.json"
    report_path.write_text(
        json.dumps(_sample_owner_daily_package_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    payload = load_kairos_owner_daily_package(report_path)

    assert payload["status"] == "REPORT_ONLY_SHORT_CYCLE_OWNER_DAILY_PACKAGE"
    assert payload["report_path"] == str(report_path)
    assert payload["accepted_edges"] == 0


def test_load_kairos_owner_daily_archive_reads_dated_bundle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    archive_dir = tmp_path / "2026-06-08"
    archive_dir.mkdir()
    (archive_dir / "owner_review_brief.json").write_text(
        json.dumps(_sample_owner_brief_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    (archive_dir / "owner_daily_package.json").write_text(
        json.dumps(_sample_owner_daily_package_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    (archive_dir / "intraday_owner_alert.json").write_text(
        json.dumps(_sample_intraday_alert_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    (archive_dir / "intraday_eod_review_queue.json").write_text(
        json.dumps(_sample_intraday_eod_review_queue_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    (archive_dir / "intraday_eod_outcome_review.json").write_text(
        json.dumps(_sample_intraday_eod_outcome_review_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "daedalus_wechat.kairos_readout.default_kairos_owner_daily_archive_root",
        lambda: tmp_path,
    )

    bundle = load_kairos_owner_daily_archive("2026-06-08")

    assert bundle["report_date"] == "2026-06-08"
    assert bundle["accepted_edges"] == 0
    assert bundle["owner_review_brief"]["report_path"] == str(
        archive_dir / "owner_review_brief.json"
    )
    assert bundle["owner_daily_package"]["report_path"] == str(
        archive_dir / "owner_daily_package.json"
    )
    assert bundle["intraday_owner_alert"]["report_path"] == str(
        archive_dir / "intraday_owner_alert.json"
    )
    assert bundle["intraday_eod_review_queue"]["report_path"] == str(
        archive_dir / "intraday_eod_review_queue.json"
    )
    assert bundle["intraday_eod_outcome_review"]["report_path"] == str(
        archive_dir / "intraday_eod_outcome_review.json"
    )


def test_format_kairos_owner_daily_archive_dates_lists_available_days(
    tmp_path: Path,
    monkeypatch,
) -> None:
    for day in ("2026-06-08", "2026-06-07"):
        archive_dir = tmp_path / day
        archive_dir.mkdir()
        (archive_dir / "owner_review_brief.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "daedalus_wechat.kairos_readout.default_kairos_owner_daily_archive_root",
        lambda: tmp_path,
    )

    text = format_kairos_owner_daily_archive_dates()

    assert "Kairos 日报历史: 可回看 2 天" in text
    assert "2026-06-08, 2026-06-07" in text
    assert "/brief YYYY-MM-DD" in text
    assert "accepted_edges=0" in text


def test_load_kairos_forward_shadow_track_record_reads_latest_report(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "short_cycle_forward_shadow_track_record_latest.json"
    report_path.write_text(
        json.dumps(_sample_forward_shadow_track_record_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    payload = load_kairos_forward_shadow_track_record(report_path)

    assert payload["status"] == "PENDING_SHORT_CYCLE_FORWARD_SHADOW_TRACK_RECORD"
    assert payload["report_path"] == str(report_path)
    assert payload["accepted_edges"] == 0


def test_load_kairos_hypothesis_scout_readout_reads_latest_report(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "short_cycle_hypothesis_scout_readout_latest.json"
    report_path.write_text(
        json.dumps(_sample_hypothesis_scout_readout_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    payload = load_kairos_hypothesis_scout_readout(report_path)

    assert payload["status"] == "REPORT_ONLY_SHORT_CYCLE_HYPOTHESIS_SCOUT_READOUT"
    assert payload["report_path"] == str(report_path)
    assert payload["accepted_edges"] == 0


def test_load_kairos_owner_review_truth_units_reads_latest_report(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "short_cycle_owner_review_truth_units_latest.json"
    report_path.write_text(
        json.dumps(_sample_owner_review_truth_units_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    payload = load_kairos_owner_review_truth_units(report_path)

    assert payload["status"] == "REPORT_ONLY_OWNER_REVIEW_TRUTH_UNITS_FROM_CACHED_RETRY"
    assert payload["report_path"] == str(report_path)
    assert payload["accepted_edges"] == 0


def test_format_kairos_owner_brief_keeps_report_only_boundary(tmp_path: Path) -> None:
    payload = _sample_owner_brief_payload()
    payload["report_path"] = str(tmp_path / "brief.json")
    package = _sample_owner_daily_package_payload()
    package["report_path"] = str(tmp_path / "package.json")

    text = format_kairos_owner_brief(
        payload,
        daily_package=package,
        intraday_alert=_sample_intraday_alert_payload(),
        intraday_eod_review_queue=_sample_intraday_eod_review_queue_payload(),
        intraday_eod_outcome_review=_sample_intraday_eod_outcome_review_payload(),
        hypothesis_scout_readout=_sample_hypothesis_scout_readout_payload(),
        owner_review_truth_units=_sample_owner_review_truth_units_payload(),
    )

    assert "Kairos 日包 brief=REPORT_ONLY_SHORT_CYCLE_OWNER_REVIEW_BRIEF" in text
    assert "accepted_edges=0" in text
    assert "不是买卖建议" in text
    assert "002251.SZ 步步高" in text
    assert "候选摘要:" in text
    assert "rows=1 labels=可用参考=1" in text
    assert "top_wounds=未行业中性/含板块beta=1" in text
    assert "gross=1.26%" in text
    assert "net=0.99%" in text
    assert "baseline=same_date_same_level_2_industry_executable_baseline" in text
    assert "cost=0.27%" in text
    assert "盘中结果: REPORT_ONLY_INTRADAY_EOD_OUTCOME_REVIEW_READY" in text
    assert "盘中结果分组:" in text
    assert "ci=[-0.52%,1.60%]" in text
    assert "tail5=43.98%" in text
    assert "p90=19.43%" in text
    assert "next_close_net=-0.05%" in text
    assert "next_close_tail5=15.08%" in text
    assert "next_follow_net=0.13%" in text
    assert "next_follow_tail5=25.15%" in text
    assert "HIGH_INDUSTRY_CONCENTRATION" in text
    assert "Owner-review truth units" in text
    assert "truth_units=REPORT_ONLY_OWNER_REVIEW_TRUTH_UNITS_FROM_CACHED_RETRY" in text
    assert "strict=9" in text
    assert "high_gap_first30m_hold horizon=next_open_to_d5_close" in text
    assert "block_condition_strict_candidates" in text
    assert "retreat_remnant_strength horizon=next_open_to_d5_close" in text
    assert "source=block_condition_daywalk not_edge=true" in text
    assert "wounds=板块条件daywalk/非主缓存路径,未接净成本,未接日期分块CI" in text
    assert "generic_daywalk_truth_units" in text
    assert (
        "open_auction_volume_price_acceptance family=auction_microstructure "
        "horizon=next_open_to_d5_close"
    ) in text
    assert "source=hypothesis_daywalk not_edge=true" in text
    assert "wounds=通用daywalk/非主缓存路径,未接净成本,未接日期分块CI" in text
    assert "score/rank is not evidence, edge, GO, or advice" in text
    assert "日包总入口" in text
    assert (
        "owner_brief=REPORT_ONLY_SHORT_CYCLE_OWNER_REVIEW_BRIEF "
        "rows=40 source=package"
    ) in text
    assert "intraday_manifest=REPORT_ONLY_SHORT_CYCLE_INTRADAY_CANDIDATE_MANIFEST" in text
    assert (
        "rows=144 symbols=41 windows=3 edge_runtime=Windows ft-edge source=package"
        in text
    )
    assert "intraday_alert=REPORT_ONLY_SHORT_CYCLE_INTRADAY_OWNER_ALERT" in text
    assert "rows=2 observed=2 pending=25 topn=20 right_tail_supp=7 clusters=2" in text
    assert (
        "intraday_trigger_readiness=TRIGGER_FIELDS_PENDING "
        "resolved=2 pending=25 pending_windows="
        "['first5m_preliminary_0936', 'first30m_confirmation_1001']"
    ) in text
    assert "intraday_alert_md=/tmp/short_cycle_intraday_owner_alert_latest.md" in text
    assert "盘中EOD复盘:" in text
    assert "候选=20 当前触发=1 曾触发=1 未触发=19 缺字段=19 events=14" in text
    assert "全A盘中观察: rows=5208 上涨=699 下跌=4470 +2=345 -2=3120" in text
    assert "候选覆盖=39/41" in text
    assert "全A盘中缺口: industry_rotation_intraday,money_effect_state_intraday" in text
    assert "09:26 opening_print_0926" in text
    assert "环境条件化 A/B 伤口" in text
    assert "denominator=24 posthoc=True" in text
    assert "routes promising=10 placebo_weak=11 not_better=3" in text
    assert "support_insufficient=0" in text
    assert "fdr pass=2 tested=24 q=0.05" in text
    assert "date_block_ci ready=24 crosses_zero=24 low_support=0" in text
    assert "diagnostic_only=true" in text
    assert "trust_gate=True trusted_axes=4 features=4" in text
    assert "diagnostic routing only; not edge" in text
    assert "T+1合法最短持有诊断" in text
    assert "horizon=next_open_to_following_close" in text
    assert "positive_net=8/30 windows=8 cost_killed=16 right_tail_ready=17" in text
    assert "prior_limit_orderly_digest net=0.88%" in text
    assert "report-only, not edge, not GO, not advice" in text
    assert "Long-window研究路由" in text
    assert (
        "machine_routes PREDICATE_SUPPORT_ADAPTATION=13 "
        "RIGHT_TAIL_FORWARD_SHADOW_OBSERVATION=8 "
        "STRICT_CANDIDATE_FORWARD_SHADOW_OBSERVATION=9 "
        "research_clock_only=true not_GO=true"
    ) in text
    assert (
        "adapt_routes PREDICATE_SUPPORT_ADAPTATION=13 "
        "RIGHT_TAIL_FORWARD_SHADOW_OBSERVATION=8 "
        "research_clock_only=true not_GO=true"
    ) in text
    assert "machine route counts are research next actions" in text
    assert "route_examples:" in text
    assert "leader_orderly_flat_pullback route=STRICT_CANDIDATE_FORWARD_SHADOW_OBSERVATION" in text
    assert "prior_limit_gap_down_reclaim route=RIGHT_TAIL_FORWARD_SHADOW_OBSERVATION" in text
    assert "cold_world_volume_exhaustion route=PREDICATE_SUPPORT_ADAPTATION" in text
    assert "follow_net=1.72% follow_tail5=40.00%" in text
    assert "route_examples_boundary=examples are research routing samples" in text
    assert "跨horizon右尾共识假设 Top 2" in text
    assert "status=REPORT_ONLY_CROSS_HORIZON_RIGHT_TAIL_CONSENSUS" in text
    assert "support_state=CROSS_HORIZON_SINGLE_WINDOW_ONLY" in text
    assert "hypotheses=17 multi_ready=0 min_windows=2 diagnostic_only=true" in text
    assert "prior_limit_gap_hold min_ready=2 same_close_net=0.68%" in text
    assert "follow_net=2.93% follow_tail5=38.89% windows=7" in text
    assert "deep_shakeout_power_recover min_ready=7" in text
    assert "legal horizon still has no validated edge, no GO, no advice" in text
    assert "Forward-shadow闭环" in text
    assert "records=244 fired=0 pending=244 following=0 following_scoreable=0" in text
    assert "pending is not failed trade, not negative edge" in text
    assert "短线暴利/右尾温度计" in text
    assert "setup=43 watchlist=20 强封无炸=12" in text
    assert "tape=RIGHT_TAIL_TAPE_ACTIVE 涨停=88 高度=5 炸板=63" in text
    assert "not a position-sizing instruction" in text
    assert "not position sizing" in text
    assert "Broad scout intake" in text
    assert (
        "cells=724 hypotheses=40 dispatchable=192 materialized_daywalk=328 "
        "specialized_readout=124 needs_spec=0 pending_surface=80"
        in text
    )
    assert "top_families 执行模板对照/execution_template_ablation=92" in text
    assert "盘中量价/intraday_price_volume=88" in text
    assert "top_hypotheses 次日开盘对前5分钟VWAP/next_open_vs_first5m_vwap_gap=32" in text
    assert (
        "dispatchable: 冰点修复首板(ice_point_repair_first_board) "
        "family=情绪周期择时/emotion_cycle_timing"
    ) in text
    assert "condition=观察冰点、退潮、高潮分歧和修复日。" in text
    assert (
        "already_materialized: 冰点修复首板(ice_point_repair_first_board) "
        "family=情绪周期择时/emotion_cycle_timing"
    ) in text
    assert "short_cycle_hypothesis_daywalk_ice_point_repair_first_board" in text
    assert "needs_spec: D3对D5衰减(d3_vs_d5_decay)" not in text
    assert (
        "pending_surface: 北向弱但活跃资金小盘(northbound_out_active_money_smallcap) "
        "family=资金偏好流/fund_preference_flow"
    ) in text
    assert "missing=canonical.northbound_flow_day" in text
    assert "scout denominator only; not evidence, not edge, not GO, not advice" in text
    assert "跨horizon右尾交集" in text
    assert "clusters=1 stocks=4 consensus=17 diagnostic_only=true" in text
    assert "support_state=CROSS_HORIZON_SINGLE_WINDOW_ONLY" in text
    assert "multi_window_ready=0 single_window_only=17 min_windows=2" in text
    assert "support_warning=cross-horizon right-tail rows with single-window support" in text
    assert "support_width_backlog status=REPORT_ONLY_CROSS_HORIZON_SUPPORT_WIDTH_BACKLOG" in text
    assert "count=17 route=EXPAND_WINDOW_SUPPORT_BEFORE_STABILITY_CLAIM" in text
    assert "research_clock_only=true" in text
    assert "prior_weak_close_reclaim_volume::小金属" in text
    assert "top=盛新锂能, 中矿资源" in text
    assert "cluster is one correlated setup; not independent stock edges" in text
    assert "弱信号观察队列 Top 1" in text
    assert "pattern-level review queue; not edge, not stock advice" in text
    assert "high_gap_first30m_hold" in text
    assert "route=NEEDS_FORWARD_SHADOW" in text
    assert "gross=1.26%" in text
    assert "net=0.99%" in text
    assert "n=1005/days=32" in text
    assert "wounds=3" in text


def test_format_kairos_owner_brief_shows_intraday_triggered_rows(
    tmp_path: Path,
) -> None:
    payload = _sample_owner_brief_payload()
    payload["report_path"] = str(tmp_path / "brief.json")
    package = _sample_owner_daily_package_payload()
    package["report_path"] = str(tmp_path / "package.json")

    text = format_kairos_owner_brief(
        payload,
        daily_package=package,
        intraday_alert=_sample_intraday_alert_payload_with_triggered_row(),
        intraday_eod_review_queue=_sample_intraday_eod_review_queue_payload(),
        intraday_eod_outcome_review=_sample_intraday_eod_outcome_review_payload(
            status="PENDING_INTRADAY_EOD_OUTCOME_PANEL_NOT_MATURED"
        ),
        hypothesis_scout_readout=_sample_hypothesis_scout_readout_payload(),
        owner_review_truth_units=_sample_owner_review_truth_units_payload(),
    )

    assert "intraday_triggered_rows=1 top_limit=8" in text
    assert "intraday_triggered_boundary=observed trigger rows only" in text
    assert "trigger #1 002251.SZ 步步高" in text
    assert (
        "windows=opening_print_0926,first5m_preliminary_0936,"
        "first30m_confirmation_1001"
    ) in text
    assert "gap=5.92%" in text
    assert "first5m=2.67%" in text
    assert "first30m=3.81%" in text
    assert "drawdown30m=-0.68%" in text
    assert "not edge, not GO, not advice" in text


def test_format_kairos_owner_brief_shows_intraday_alert_blocker() -> None:
    text = format_kairos_owner_brief(
        _sample_owner_brief_payload(),
        daily_package=_sample_owner_daily_package_payload(),
        intraday_alert=_sample_future_blocked_intraday_alert_payload(),
        intraday_eod_review_queue=_sample_intraday_eod_review_queue_payload(),
    )

    assert "intraday_alert=BLOCKED_SHORT_CYCLE_INTRADAY_OWNER_ALERT" in text
    assert "snapshot=BLOCKED_SNAPSHOT_FUTURE_TIMESTAMP" in text
    assert "intraday_alert_blocker reason=BLOCKED_SNAPSHOT_FUTURE_TIMESTAMP" in text
    assert "generated=2026-06-07T21:17:39Z" in text
    assert "max_observation=2026-06-08T01:26:05+00:00" in text
    assert "errors=realtime_snapshot_future_timestamp" in text


def test_format_kairos_owner_brief_falls_back_when_package_lacks_brief() -> None:
    payload = _sample_owner_brief_payload()
    package = _sample_owner_daily_package_payload()
    package.pop("owner_review_brief")

    text = format_kairos_owner_brief(payload, daily_package=package)

    assert (
        "owner_brief=REPORT_ONLY_SHORT_CYCLE_OWNER_REVIEW_BRIEF "
        "rows=1 source=latest_owner_brief_fallback"
    ) in text


def test_format_kairos_owner_brief_uses_track_record_fallback() -> None:
    payload = _sample_owner_brief_payload()
    package = _sample_owner_daily_package_payload()
    package.pop("forward_shadow_track_record")

    text = format_kairos_owner_brief(
        payload,
        daily_package=package,
        forward_shadow_track_record=_sample_forward_shadow_track_record_payload(),
    )

    assert "Forward-shadow闭环" in text
    assert "source=PENDING_SHORT_CYCLE_FORWARD_SHADOW_TRACK_RECORD" in text
    assert "open_state_waterline=2026-06-05" in text
    assert "target_open_state@2026-06-08 count=244" in text
    assert "pending is not failed trade, not negative edge" in text


def test_format_kairos_owner_brief_merges_track_record_fallback_fields() -> None:
    payload = _sample_owner_brief_payload()
    package = _sample_owner_daily_package_payload()

    text = format_kairos_owner_brief(
        payload,
        daily_package=package,
        forward_shadow_track_record=_sample_forward_shadow_track_record_payload(),
    )

    assert "Forward-shadow闭环" in text
    assert "source=PENDING_SHORT_CYCLE_FORWARD_SHADOW_TRACK_RECORD" in text
    assert "as_of=2026-06-05 target=2026-06-08" in text
    assert "open_state_waterline=2026-06-05" in text
    assert "target_open_state@2026-06-08 count=244" in text


def test_format_kairos_owner_brief_falls_back_when_package_lacks_intraday_manifest() -> None:
    payload = _sample_owner_brief_payload()
    package = _sample_owner_daily_package_payload()
    package.pop("intraday_candidate_manifest")

    text = format_kairos_owner_brief(
        payload,
        daily_package=package,
        intraday_manifest=_sample_intraday_manifest_payload(),
    )

    assert "intraday_manifest=REPORT_ONLY_SHORT_CYCLE_INTRADAY_CANDIDATE_MANIFEST" in text
    assert (
        "rows=144 symbols=41 windows=3 edge_runtime=Windows ft-edge "
        "source=latest_intraday_manifest_fallback"
    ) in text
    assert "10:01 first30m_confirmation_1001" in text
    assert "intraday_md=/tmp/short_cycle_intraday_candidate_manifest_latest.md" in text


def test_format_kairos_owner_brief_compact_is_owner_visible() -> None:
    text = format_kairos_owner_brief_compact(
        _sample_owner_brief_payload(),
        daily_package=_sample_owner_daily_package_payload(),
        intraday_alert=_sample_intraday_alert_payload_with_triggered_row(),
        intraday_eod_review_queue=_sample_intraday_eod_review_queue_payload(),
        hypothesis_scout_readout=_sample_hypothesis_scout_readout_payload(),
        owner_review_truth_units=_sample_owner_review_truth_units_payload(),
        owner_feedback_summary={
            "feedback_count": 2,
            "mark_counts": {"useful": 1, "noise": 1},
            "recent_feedback": [
                {"mark": "useful", "text": "高开承接值得继续观察"},
            ],
            "accepted_edges": 0,
        },
        owner_feedback_route_intake={
            "status": "REPORT_ONLY_OWNER_FEEDBACK_RESEARCH_ROUTE_INTAKE_READY",
            "queue_item_count": 2,
            "source_total_route_item_count": 2,
            "research_action_counts": {
                "draft_machine_executable_hypothesis_or_selection_policy": 1,
                "verify_surface_or_wound_connection_before_rerun": 1,
            },
            "next_actions": [
                {
                    "action": (
                        "draft_machine_executable_hypothesis_or_selection_policy"
                    ),
                    "count": 1,
                }
            ],
            "accepted_edges": 0,
        },
        candidate_limit=2,
    )

    assert "Kairos 日包 2026-06-05 -> 2026-06-08" in text
    assert "accepted_edges=0" in text
    assert "非买卖建议" in text
    assert "市场: 震荡 情绪=热" in text
    assert "行业集中: 行业高度集中" in text
    assert "右尾温度计:" in text
    assert "环境诊断: cases=24 当前候选=0 FDR过=2/6" in text
    assert "CI未穿0=2 CI穿0=3 posthoc=6 伤口=4" in text
    assert "边界=report-only" in text
    assert "盘中: 观察包就绪 已观察=2 待观察=25" in text
    assert "触发字段=触发字段就绪 快照=实时快照待补" in text
    assert "盘中EOD复盘: PENDING_EOD_INTRADAY_REPLAY_REVIEW" in text
    assert "盘中结果: PENDING_INTRADAY_EOD_OUTCOME_PANEL_NOT_MATURED" in text
    assert "盘中结果阻塞: target_trade_date_outcome_rows_not_matured" in text
    assert "全A盘中观察: rows=5208 上涨=699 下跌=4470" in text
    assert "盘中触发 Top 1" in text
    assert "高开后前30分钟承接 窗口=开盘,前5分钟,前30分钟确认" in text
    assert "窗口=开盘,前5分钟,前30分钟确认" in text
    assert "明天重点 Top 1" in text
    assert "战法条件: 高开后前30分钟承接: 高开后没有快速转弱" in text
    assert "优先看强势股池、流动性可交易" in text
    assert "002251.SZ 步步高" in text
    assert "净超额=" in text
    assert "样本=" in text
    assert "伤口=未行业中性/含板块beta" in text
    assert "研究队列:" in text
    assert "可审单元=120 严格候选=9 右尾观察=23" in text
    assert "专用readout=124 待定义=0" in text
    assert "已跑结果: truth_units=304 严格=35 右尾=26" in text
    assert "support不足=120 成本缺=69 成本杀=5 右尾负均值=49" in text
    assert "反馈回路: 已记录=2 useful=1 noise=1" in text
    assert "不改证据门/排名" in text
    assert "反馈接入Kairos: REPORT_ONLY_OWNER_FEEDBACK_RESEARCH_ROUTE_INTAKE_READY" in text
    assert "queue=2 source_total=2" in text
    assert "draft_machine_executable_hypothesis_or_selection_policy=1" in text
    assert "verify_surface_or_wound_connection_before_rerun=1" in text
    assert "边界=只导研究,不改证据门/排名" in text
    assert "证据覆盖: 窗口=7 horizon=3 多窗单元=64" in text
    assert "Scout重点:" in text
    assert "执行模板对照=92" in text
    assert "盘中量价=88" in text
    assert "Scout条件: 执行模板对照: 比较次日开盘" in text
    assert "Scout待定义:" not in text
    assert "REPORT_ONLY_SHORT_CYCLE_INTRADAY_OWNER_ALERT" not in text
    assert "first30m_confirmation_1001" not in text
    assert "完整诊断: /brief full；盘中: /intraday" in text
    assert "Long-window研究路由" not in text


def test_cli_brief_does_not_require_bridge_state(tmp_path: Path, capsys, monkeypatch) -> None:
    report_path = tmp_path / "short_cycle_owner_review_brief_latest.json"
    report_path.write_text(
        json.dumps(_sample_owner_brief_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["daedalus-wechat", "brief", "--report-path", str(report_path), "--limit", "1"],
    )
    monkeypatch.setattr(
        "daedalus_wechat.cli.load_kairos_owner_daily_package",
        lambda: _sample_owner_daily_package_payload(),
    )
    monkeypatch.setattr(
        "daedalus_wechat.cli.load_kairos_intraday_candidate_manifest",
        lambda: _sample_intraday_manifest_payload(),
    )
    monkeypatch.setattr(
        "daedalus_wechat.cli.load_kairos_forward_shadow_track_record",
        lambda: _sample_forward_shadow_track_record_payload(),
    )
    monkeypatch.setattr(
        "daedalus_wechat.cli.load_kairos_hypothesis_scout_readout",
        lambda: _sample_hypothesis_scout_readout_payload(),
    )

    rc = main()

    assert rc == 0
    out = capsys.readouterr().out
    assert "Kairos 日包 2026-06-05 -> 2026-06-08" in out
    assert "研究队列:" in out
    assert "Scout重点:" in out
    assert "002251.SZ 步步高" in out


def test_cli_brief_date_reads_archived_daily_report(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    archive_dir = tmp_path / "2026-06-08"
    archive_dir.mkdir()
    (archive_dir / "owner_review_brief.json").write_text(
        json.dumps(_sample_owner_brief_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    (archive_dir / "owner_daily_package.json").write_text(
        json.dumps(_sample_owner_daily_package_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    (archive_dir / "intraday_owner_alert.json").write_text(
        json.dumps(_sample_intraday_alert_payload_with_triggered_row(), ensure_ascii=False),
        encoding="utf-8",
    )
    (archive_dir / "intraday_eod_review_queue.json").write_text(
        json.dumps(_sample_intraday_eod_review_queue_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "daedalus_wechat.kairos_readout.default_kairos_owner_daily_archive_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "sys.argv",
        ["daedalus-wechat", "brief", "--date", "2026-06-08", "--limit", "1"],
    )
    monkeypatch.setattr(
        "daedalus_wechat.cli.load_kairos_intraday_candidate_manifest",
        lambda: _sample_intraday_manifest_payload(),
    )
    monkeypatch.setattr(
        "daedalus_wechat.cli.load_kairos_forward_shadow_track_record",
        lambda: _sample_forward_shadow_track_record_payload(),
    )
    monkeypatch.setattr(
        "daedalus_wechat.cli.load_kairos_hypothesis_scout_readout",
        lambda: _sample_hypothesis_scout_readout_payload(),
    )

    rc = main()

    assert rc == 0
    out = capsys.readouterr().out
    assert "Kairos 日包 2026-06-05 -> 2026-06-08" in out
    assert f"brief={archive_dir / 'owner_review_brief.json'}" in out
    assert "盘中触发 Top 1" in out
    assert "盘中EOD复盘: PENDING_EOD_INTRADAY_REPLAY_REVIEW" in out


def test_cli_brief_dates_lists_archive_dates(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    archive_dir = tmp_path / "2026-06-08"
    archive_dir.mkdir()
    (archive_dir / "owner_review_brief.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "daedalus_wechat.kairos_readout.default_kairos_owner_daily_archive_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr("sys.argv", ["daedalus-wechat", "brief", "--dates"])

    rc = main()

    assert rc == 0
    out = capsys.readouterr().out
    assert "Kairos 日报历史: 可回看 1 天" in out
    assert "2026-06-08" in out


def test_cli_brief_full_keeps_diagnostic_view(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    report_path = tmp_path / "short_cycle_owner_review_brief_latest.json"
    report_path.write_text(
        json.dumps(_sample_owner_brief_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "daedalus-wechat",
            "brief",
            "--report-path",
            str(report_path),
            "--limit",
            "1",
            "--full",
        ],
    )
    monkeypatch.setattr(
        "daedalus_wechat.cli.load_kairos_owner_daily_package",
        lambda: _sample_owner_daily_package_payload(),
    )
    monkeypatch.setattr(
        "daedalus_wechat.cli.load_kairos_intraday_candidate_manifest",
        lambda: _sample_intraday_manifest_payload(),
    )
    monkeypatch.setattr(
        "daedalus_wechat.cli.load_kairos_forward_shadow_track_record",
        lambda: _sample_forward_shadow_track_record_payload(),
    )
    monkeypatch.setattr(
        "daedalus_wechat.cli.load_kairos_hypothesis_scout_readout",
        lambda: _sample_hypothesis_scout_readout_payload(),
    )

    rc = main()

    assert rc == 0
    out = capsys.readouterr().out
    assert "Kairos 日包 brief=REPORT_ONLY_SHORT_CYCLE_OWNER_REVIEW_BRIEF" in out
    assert "日包总入口" in out
    assert "Broad scout intake" in out


def test_daemon_brief_command_is_read_only() -> None:
    with patch(
        "daedalus_wechat.daemon.load_kairos_owner_brief",
        return_value=_sample_owner_brief_payload(),
    ), patch(
        "daedalus_wechat.daemon.load_kairos_owner_daily_package",
        return_value=_sample_owner_daily_package_payload(),
    ), patch(
        "daedalus_wechat.daemon.load_kairos_intraday_candidate_manifest",
        return_value=_sample_intraday_manifest_payload(),
    ), patch(
        "daedalus_wechat.daemon.load_kairos_intraday_alert",
        return_value=_sample_intraday_alert_payload(),
    ), patch(
        "daedalus_wechat.daemon.load_kairos_forward_shadow_track_record",
        return_value=_sample_forward_shadow_track_record_payload(),
    ), patch(
        "daedalus_wechat.daemon.load_kairos_hypothesis_scout_readout",
        return_value=_sample_hypothesis_scout_readout_payload(),
    ):
        text = BridgeDaemon._handle_command(BridgeDaemon.__new__(BridgeDaemon), "/brief")

    assert "Kairos 日包 2026-06-05 -> 2026-06-08" in text
    assert "accepted_edges=0" in text
    assert "完整诊断: /brief full；盘中: /intraday" in text


def test_daemon_brief_full_command_keeps_diagnostic_view() -> None:
    with patch(
        "daedalus_wechat.daemon.load_kairos_owner_brief",
        return_value=_sample_owner_brief_payload(),
    ), patch(
        "daedalus_wechat.daemon.load_kairos_owner_daily_package",
        return_value=_sample_owner_daily_package_payload(),
    ), patch(
        "daedalus_wechat.daemon.load_kairos_intraday_candidate_manifest",
        return_value=_sample_intraday_manifest_payload(),
    ), patch(
        "daedalus_wechat.daemon.load_kairos_intraday_alert",
        return_value=_sample_intraday_alert_payload(),
    ), patch(
        "daedalus_wechat.daemon.load_kairos_forward_shadow_track_record",
        return_value=_sample_forward_shadow_track_record_payload(),
    ), patch(
        "daedalus_wechat.daemon.load_kairos_hypothesis_scout_readout",
        return_value=_sample_hypothesis_scout_readout_payload(),
    ):
        text = BridgeDaemon._handle_command(
            BridgeDaemon.__new__(BridgeDaemon), "/brief full"
        )

    assert "Kairos 日包 brief=REPORT_ONLY_SHORT_CYCLE_OWNER_REVIEW_BRIEF" in text
    assert "Forward-shadow闭环" in text
    assert "Broad scout intake" in text


def test_daemon_brief_date_command_reads_archive() -> None:
    with patch(
        "daedalus_wechat.daemon.load_kairos_owner_daily_archive",
        return_value={
            "owner_review_brief": _sample_owner_brief_payload(),
            "owner_daily_package": _sample_owner_daily_package_payload(),
            "intraday_owner_alert": _sample_intraday_alert_payload_with_triggered_row(),
            "intraday_eod_review_queue": _sample_intraday_eod_review_queue_payload(),
            "intraday_eod_outcome_review": _sample_intraday_eod_outcome_review_payload(),
            "accepted_edges": 0,
        },
    ) as archive_loader, patch(
        "daedalus_wechat.daemon.load_kairos_intraday_candidate_manifest",
        return_value=_sample_intraday_manifest_payload(),
    ), patch(
        "daedalus_wechat.daemon.load_kairos_forward_shadow_track_record",
        return_value=_sample_forward_shadow_track_record_payload(),
    ), patch(
        "daedalus_wechat.daemon.load_kairos_hypothesis_scout_readout",
        return_value=_sample_hypothesis_scout_readout_payload(),
    ):
        text = BridgeDaemon._handle_command(
            BridgeDaemon.__new__(BridgeDaemon), "/brief 2026-06-08"
        )

    archive_loader.assert_called_once_with("2026-06-08")
    assert "Kairos 日包 2026-06-05 -> 2026-06-08" in text
    assert "盘中触发 Top 1" in text
    assert "盘中EOD复盘: PENDING_EOD_INTRADAY_REPLAY_REVIEW" in text


def test_daemon_brief_dates_command_lists_archive_dates() -> None:
    with patch(
        "daedalus_wechat.daemon.format_kairos_owner_daily_archive_dates",
        return_value="Kairos 日报历史: 可回看 1 天",
    ):
        text = BridgeDaemon._handle_command(
            BridgeDaemon.__new__(BridgeDaemon), "/brief dates"
        )

    assert "Kairos 日报历史" in text


def test_load_kairos_intraday_alert_reads_latest_report(tmp_path: Path) -> None:
    report_path = tmp_path / "short_cycle_intraday_owner_alert_latest.json"
    report_path.write_text(
        json.dumps(_sample_intraday_alert_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    payload = load_kairos_intraday_alert(report_path)

    assert payload["status"] == "REPORT_ONLY_SHORT_CYCLE_INTRADAY_OWNER_ALERT"
    assert payload["report_path"] == str(report_path)
    assert payload["accepted_edges"] == 0


def test_load_kairos_intraday_candidate_manifest_reads_latest_report(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "short_cycle_intraday_candidate_manifest_latest.json"
    report_path.write_text(
        json.dumps(_sample_intraday_manifest_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    payload = load_kairos_intraday_candidate_manifest(report_path)

    assert payload["status"] == "REPORT_ONLY_SHORT_CYCLE_INTRADAY_CANDIDATE_MANIFEST"
    assert payload["report_path"] == str(report_path)
    assert payload["accepted_edges"] == 0


def test_load_kairos_intraday_eod_review_queue_reads_latest_report(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "short_cycle_intraday_eod_review_queue_latest.json"
    report_path.write_text(
        json.dumps(_sample_intraday_eod_review_queue_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    payload = load_kairos_intraday_eod_review_queue(report_path)

    assert payload["status"] == "PENDING_EOD_INTRADAY_REPLAY_REVIEW"
    assert payload["report_path"] == str(report_path)
    assert payload["accepted_edges"] == 0


def test_load_kairos_intraday_eod_outcome_review_reads_latest_report(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "short_cycle_intraday_eod_outcome_review_latest.json"
    report_path.write_text(
        json.dumps(
            _sample_intraday_eod_outcome_review_payload(),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = load_kairos_intraday_eod_outcome_review(report_path)

    assert payload["status"] == "REPORT_ONLY_INTRADAY_EOD_OUTCOME_REVIEW_READY"
    assert payload["report_path"] == str(report_path)
    assert payload["accepted_edges"] == 0


def test_format_kairos_intraday_alert_keeps_report_only_boundary(
    tmp_path: Path,
) -> None:
    payload = _sample_intraday_alert_payload()
    payload["report_path"] = str(tmp_path / "intraday.json")

    text = format_kairos_intraday_alert(payload)

    assert "Kairos 盘中 alert=REPORT_ONLY_SHORT_CYCLE_INTRADAY_OWNER_ALERT" in text
    assert "accepted_edges=0" in text
    assert "不是买卖建议" in text
    assert "不是GO" in text
    assert "002251.SZ 步步高" in text
    assert "alert_sources topn=20 right_tail_supp=7 clusters=2" in text
    assert "右尾补充候选 Top 1" in text
    assert "002240.SZ 盛新锂能" in text
    assert "prior_weak_close_reclaim_volume::小金属" in text
    assert "PENDING_REALTIME_SNAPSHOT" in text


def test_format_kairos_intraday_alert_highlights_triggered_rows() -> None:
    text = format_kairos_intraday_alert(
        _sample_intraday_alert_payload_with_triggered_row()
    )

    assert "盘中已触发:" in text
    assert "intraday_triggered_rows=1 top_limit=8" in text
    assert "trigger #1 002251.SZ 步步高" in text
    assert "first30m=3.81%" in text
    assert "drawdown30m=-0.68%" in text
    assert "intraday_triggered_boundary=observed trigger rows only" in text


def test_format_kairos_intraday_alert_shows_blocked_snapshot_details() -> None:
    text = format_kairos_intraday_alert(
        _sample_future_blocked_intraday_alert_payload()
    )

    assert "Kairos intraday=BLOCKED_SHORT_CYCLE_INTRADAY_OWNER_ALERT" in text
    assert "intraday_alert_blocker reason=BLOCKED_SNAPSHOT_FUTURE_TIMESTAMP" in text
    assert "snapshot_time=2026-06-08T09:26:05+08:00" in text
    assert "max_observation=2026-06-08T01:26:05+00:00" in text
    assert "error=realtime_snapshot_future_timestamp" in text
    assert "accepted_edges=0" in text


def test_cli_intraday_does_not_require_bridge_state(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    report_path = tmp_path / "short_cycle_intraday_owner_alert_latest.json"
    report_path.write_text(
        json.dumps(_sample_intraday_alert_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "daedalus-wechat",
            "intraday",
            "--report-path",
            str(report_path),
            "--limit",
            "1",
        ],
    )

    rc = main()

    assert rc == 0
    out = capsys.readouterr().out
    assert "Kairos 盘中 alert=REPORT_ONLY_SHORT_CYCLE_INTRADAY_OWNER_ALERT" in out
    assert "002251.SZ 步步高" in out
    assert "右尾补充候选 Top 1" in out
    assert "002240.SZ 盛新锂能" in out


def test_daemon_intraday_command_is_read_only() -> None:
    with patch(
        "daedalus_wechat.daemon.load_kairos_intraday_alert",
        return_value=_sample_intraday_alert_payload(),
    ):
        text = BridgeDaemon._handle_command(
            BridgeDaemon.__new__(BridgeDaemon),
            "/intraday",
        )

    assert "Kairos 盘中 alert=REPORT_ONLY_SHORT_CYCLE_INTRADAY_OWNER_ALERT" in text
    assert "accepted_edges=0" in text
