#!/usr/bin/env python3
"""Create PEFT labels resolved with newly uploaded original documents.

This script does not modify the original ChatGPT labels, eval files, or the
conservative salvage output. It writes a separate raw-resolved label file and a
human-readable report for the remaining review cases.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path("outputs/peft/answer_labels_salvaged_conservative.jsonl")
DEFAULT_OUTPUT = Path("outputs/peft/answer_labels_raw_resolved.jsonl")
DEFAULT_REPORT = Path("outputs/peft/raw_original_review/raw_original_resolution_report.md")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def resolution(
    *,
    answer: str,
    evidence_documents: list[str],
    evidence_sentences: list[str],
    normalized_values: dict[str, Any],
    confidence: str,
    raw_status: str,
    raw_notes: str,
) -> dict[str, Any]:
    return {
        "answer": answer,
        "evidence_documents": evidence_documents,
        "evidence_sentences": evidence_sentences,
        "normalized_values": normalized_values,
        "confidence": confidence,
        "needs_human_review": False,
        "review_reason": "",
        "trainable": True,
        "salvage_status": "raw_original_resolved",
        "salvage_policy": "original_document_review_resolution",
        "raw_original_review": {
            "status": raw_status,
            "notes": raw_notes,
        },
    }


RAW_RESOLUTIONS: dict[str, dict[str, Any]] = {
    "Q003": resolution(
        answer=(
            "KOICA 전자조달 「우즈베키스탄 열린 의정활동 상하원 국회 방송시스템 구축 및 지역의회 연계 개선 PMC 용역」의 "
            "예산 규모는 집행 한도액 기준 6,758,571,493원입니다. 원문에는 이 금액이 달러 기준 "
            "$5,198,901, 2024년 기준환율 1달러=1,300원을 적용한 금액으로 제시되어 있습니다. "
            "근거 문서: KOICA 전자조달_[긴급] [지문] [국제] 우즈베키스탄 열린 의정활동 상하원 .hwp. "
            "근거 문장: \"집행 한도액 : 6,758,571,493원($5,198,901/1$=1,300원, 2024년 기준환율)\"."
        ),
        evidence_documents=["KOICA 전자조달_[긴급] [지문] [국제] 우즈베키스탄 열린 의정활동 상하원 .hwp"],
        evidence_sentences=[
            "집행 한도액 : 6,758,571,493원($5,198,901/1$=1,300원, 2024년 기준환율)",
            "본 사업은 40억원 이상 80억원 미만 사업으로 ...",
        ],
        normalized_values={
            "project_budget": "6,758,571,493원",
            "project_budget_krw": 6758571493,
            "usd_budget": "$5,198,901",
            "exchange_rate": "1$=1,300원",
        },
        confidence="high",
        raw_status="resolved",
        raw_notes="기존 source_store의 2,000,000,000원 후보는 원문에서 직접 확인되지 않았고, 원문 집행 한도액이 확인됨.",
    ),
    "Q013": resolution(
        answer=(
            "세 사업의 핵심 개선 목적과 예산은 다음과 같습니다. "
            "1) 고려대학교 차세대 포털·학사 정보시스템은 노후화된 학사 시스템과 업무별로 분산된 정보화를 통합하고, "
            "교내 구성원의 정보서비스 접근성과 데이터 기반 대학경영 지원을 개선하는 데 초점이 있습니다. 예산은 11,270,000,000원입니다. "
            "2) GKL 그룹웨어 시스템은 그룹웨어·기록물관리·사내SNS·메신저 시스템 노후화와 비표준/보안취약점 문제를 개선하고, "
            "웹 기반 업무환경과 사용자 편의성을 높이는 데 초점이 있습니다. 원문 예산은 1,515,000천원이며 환산하면 1,515,000,000원입니다. "
            "3) 인천광역시 도시계획위원회 통합관리시스템은 통합관리시스템 부재로 인한 개별 처리, 외부위원 대상 메일 배포로 인한 보안 문제를 개선하고, "
            "위원회별·안건별 통합관리 및 자료 활용 체계를 구축하는 데 초점이 있습니다. 예산은 150,000,000원입니다."
        ),
        evidence_documents=[
            "고려대학교_차세대 포털·학사 정보시스템 구축사업.pdf",
            "그랜드코리아레저(주)_2024년도 GKL 그룹웨어 시스템 구축 용역.hwp",
            "인천광역시_도시계획위원회 통합관리시스템 구축용역.hwp",
        ],
        evidence_sentences=[
            "사업예산 : 11,270,000,000원 (V.A.T 포함, 3년 분할 지급)",
            "분산된 시스템 및 데이터의 통합 ... 시스템 통합에 대한 요구가 증가함",
            "사업예산 : 1,515,000천원 (부가세 포함)",
            "그룹웨어 및 기록물관리, 사내SNS(별별얘기), 메신저 시스템 노후화 ... 개선 필요",
            "사 업 비: 금150,000,000원 (VAT 포함)",
            "통합관리시스템 부재로 업무별 개별 처리 ... 위원회별, 안건별 현황관리체계 구축 필요",
        ],
        normalized_values={
            "budgets": {
                "고려대학교": {"raw": "11,270,000,000원", "krw": 11270000000},
                "그랜드코리아레저(주)": {"raw": "1,515,000천원", "krw": 1515000000},
                "인천광역시": {"raw": "150,000,000원", "krw": 150000000},
            }
        },
        confidence="high",
        raw_status="resolved",
        raw_notes="원문 3개 문서에서 각 예산과 목적/문제점 근거를 모두 확인.",
    ),
    "Q019": resolution(
        answer=(
            "코이카(KOICA) 전자조달의 우즈베키스탄 국회 방송시스템 구축 사업 총 예산은 원문 집행 한도액 기준 "
            "6,758,571,493원입니다. 원문에는 $5,198,901을 2024년 기준환율 1달러=1,300원으로 환산한 금액으로 제시되어 있습니다. "
            "근거 문서: KOICA 전자조달_[긴급] [지문] [국제] 우즈베키스탄 열린 의정활동 상하원 .hwp. "
            "근거 문장: \"집행 한도액 : 6,758,571,493원($5,198,901/1$=1,300원, 2024년 기준환율)\"."
        ),
        evidence_documents=["KOICA 전자조달_[긴급] [지문] [국제] 우즈베키스탄 열린 의정활동 상하원 .hwp"],
        evidence_sentences=["집행 한도액 : 6,758,571,493원($5,198,901/1$=1,300원, 2024년 기준환율)"],
        normalized_values={
            "project_budget": "6,758,571,493원",
            "project_budget_krw": 6758571493,
            "usd_budget": "$5,198,901",
            "exchange_rate": "1$=1,300원",
        },
        confidence="high",
        raw_status="resolved",
        raw_notes="오타가 있는 질문이지만 대상 문서와 예산 근거가 원문에서 명확히 확인됨.",
    ),
    "Q027": resolution(
        answer=(
            "차액은 문서에서 확인할 수 없습니다. KOICA 사업의 예산은 원문에서 집행 한도액 6,758,571,493원으로 확인되지만, "
            "한국수자원공사 「용인 첨단 시스템반도체 국가산단 용수공급사업 타당성조사」 원문에서는 용역 예산/사업비 금액이 확인되지 않습니다. "
            "따라서 두 사업 예산의 차액은 계산할 수 없습니다. "
            "근거 문서: KOICA 전자조달_[긴급] [지문] [국제] 우즈베키스탄 열린 의정활동 상하원 .hwp, "
            "한국수자원공사_용인 첨단 시스템반도체 국가산단 용수공급사업 타당성.hwp. "
            "근거 문장: \"집행 한도액 : 6,758,571,493원...\" 및 한국수자원공사 문서의 과업지시서 본문에서는 예산 금액 미확인."
        ),
        evidence_documents=[
            "KOICA 전자조달_[긴급] [지문] [국제] 우즈베키스탄 열린 의정활동 상하원 .hwp",
            "한국수자원공사_용인 첨단 시스템반도체 국가산단 용수공급사업 타당성.hwp",
        ],
        evidence_sentences=[
            "집행 한도액 : 6,758,571,493원($5,198,901/1$=1,300원, 2024년 기준환율)",
            "한국수자원공사 원문에서는 사업예산/사업비/용역금액의 직접 금액 표기를 확인하지 못함",
        ],
        normalized_values={
            "koica_budget_krw": 6758571493,
            "kwater_budget_krw": None,
            "difference_krw": None,
        },
        confidence="medium",
        raw_status="partial_grounded_refusal",
        raw_notes="KOICA 금액은 원문으로 해결됐지만 한국수자원공사 예산 금액은 원문에서 확인되지 않음.",
    ),
    "Q028": resolution(
        answer=(
            "두 사업 중 예산이 더 큰 것은 고려대학교 「차세대 포털·학사 정보시스템 구축사업」입니다. "
            "고려대학교 사업예산은 11,270,000,000원이고, 인천광역시 「도시계획위원회 통합관리시스템 구축용역」의 사업비는 150,000,000원입니다. "
            "따라서 고려대학교 사업의 예산이 더 큽니다."
        ),
        evidence_documents=[
            "고려대학교_차세대 포털·학사 정보시스템 구축사업.pdf",
            "인천광역시_도시계획위원회 통합관리시스템 구축용역.hwp",
        ],
        evidence_sentences=[
            "사업예산 : 11,270,000,000원 (V.A.T 포함, 3년 분할 지급)",
            "사 업 비: 금150,000,000원 (VAT 포함)",
        ],
        normalized_values={
            "larger_project": "고려대학교_차세대 포털·학사 정보시스템 구축사업",
            "korea_univ_budget_krw": 11270000000,
            "incheon_budget_krw": 150000000,
        },
        confidence="high",
        raw_status="resolved",
        raw_notes="원문 2개 문서에서 양쪽 예산 모두 확인.",
    ),
    "Q031": resolution(
        answer=(
            "국립중앙의료원 사업은 응급의료 상황관리 업무, 특히 중증응급환자의 병원 선정, 병원 간 전원, 재난 조정 업무를 위한 "
            "IP 기반 콜센터와 중앙·광역 상황실 처리 시스템 구축에 초점이 있습니다. 반면 GKL 그룹웨어 사업은 그룹웨어, 기록물관리, 사내SNS, "
            "메신저 등 내부 업무시스템의 노후화와 비표준/보안취약점을 개선하여 웹 기반 업무환경과 사용자 편의성을 높이는 데 초점이 있습니다."
        ),
        evidence_documents=[
            "국립중앙의료원_(긴급)「2024년도 차세대 응급의료 상황관리시스템 구축.hwp",
            "그랜드코리아레저(주)_2024년도 GKL 그룹웨어 시스템 구축 용역.hwp",
        ],
        evidence_sentences=[
            "전국 중증응급질환자 병원 선정, 병원 간 전원 및 재난 조정 업무를 위한 IP기반 콜센터 구축",
            "중앙상황실의 전원접수 및 재난상황접수 처리를 위한 시스템 구축",
            "그룹웨어 및 기록물관리, 사내SNS(별별얘기), 메신저 시스템 노후화 ... 개선 필요",
            "사용자의 편의성을 최우선으로 고려하여 업무프로세스 재설계 및 업무 환경 개선",
        ],
        normalized_values={},
        confidence="high",
        raw_status="resolved",
        raw_notes="원문 2개 문서에서 목적과 범위 근거 확인.",
    ),
    "Q033": resolution(
        answer=(
            "세 사업은 공통적으로 기존 시스템이 분산·개별 운영되어 정보 연계, 현황 파악, 업무 처리 효율이 떨어지는 문제를 해결하려는 성격이 있습니다. "
            "고려대학교는 노후 학사 시스템과 업무별 분산 정보화, 정보연계 미흡을 개선하려 하고, 국립중앙의료원은 병원 선정·전원·재난 상황 접수를 "
            "중앙/광역 상황실 시스템으로 처리하려 하며, 인천광역시는 위원회 업무가 개별 처리되고 외부위원 자료가 메일로 배포되는 한계를 통합관리시스템으로 개선하려 합니다. "
            "세 사업의 합산 예산은 고려대학교 11,270,000,000원 + 국립중앙의료원 1,400,000,000원 + 인천광역시 150,000,000원 = 12,820,000,000원입니다."
        ),
        evidence_documents=[
            "고려대학교_차세대 포털·학사 정보시스템 구축사업.pdf",
            "국립중앙의료원_(긴급)「2024년도 차세대 응급의료 상황관리시스템 구축.hwp",
            "인천광역시_도시계획위원회 통합관리시스템 구축용역.hwp",
        ],
        evidence_sentences=[
            "사업예산 : 11,270,000,000원 (V.A.T 포함, 3년 분할 지급)",
            "분산된 시스템 및 데이터의 통합 ... 시스템 통합에 대한 요구가 증가함",
            "사업예산 : 금일십사억원정 (￦1,400,000,000원, VAT포함)",
            "중앙상황실의 전원접수 및 재난상황접수 처리를 위한 시스템 구축",
            "사 업 비: 금150,000,000원 (VAT 포함)",
            "통합관리시스템 부재로 업무별 개별 처리 ... 위원회별, 안건별 현황관리체계 구축 필요",
        ],
        normalized_values={
            "korea_univ_budget_krw": 11270000000,
            "nmc_budget_krw": 1400000000,
            "incheon_budget_krw": 150000000,
            "total_budget_krw": 12820000000,
        },
        confidence="high",
        raw_status="resolved",
        raw_notes="원문 3개 문서에서 예산과 시스템 단절/통합 필요성 근거 확인.",
    ),
    "Q034": resolution(
        answer=(
            "예산 규모를 큰 금액부터 정리하면 다음과 같습니다. "
            "1) KOICA 우즈베키스탄 열린 의정활동 상하원 국회 방송시스템 사업: 대상국은 우즈베키스탄이며, 핵심 인프라는 상·하원 국회 방송시스템과 지역의회 연계 기반입니다. 예산은 집행 한도액 6,758,571,493원입니다. "
            "2) 아시아물위원회 우즈벡-키르기즈스탄 기후변화대응 스마트 관개시스템 사업: 대상국은 키르기즈스탄과 우즈베키스탄이며, 핵심 인프라는 스마트 양수·수문 기반 관개/수자원 관리입니다. 예산은 5,031,000,000원입니다. "
            "3) 한국수출입은행 모잠비크 마푸토 ITS 구축사업 F/S: 대상국은 모잠비크이며, 핵심 인프라는 지능형교통시스템(ITS) 구축을 위한 타당성조사와 교통/센터 시스템 계획입니다. 예산은 1,247,000,000원입니다."
        ),
        evidence_documents=[
            "KOICA 전자조달_[긴급] [지문] [국제] 우즈베키스탄 열린 의정활동 상하원 .hwp",
            "사단법인아시아물위원회사무국_우즈벡-키르기즈스탄 기후변화대응 스.hwp",
            "한국수출입은행_(긴급) 모잠비크 마푸토 지능형교통시스템(ITS) 구축사업.hwp",
        ],
        evidence_sentences=[
            "대 상 지 : 우즈베키스탄 타슈켄트시, 12개 주(州) 및 카라칼팍스탄 공화국",
            "집행 한도액 : 6,758,571,493원($5,198,901/1$=1,300원, 2024년 기준환율)",
            "용역금액 : 5,031,000,000원 (손해배상보험(공제)료 포함)",
            "사업목적 : 스마트 양수 및 수문 설치를 통하여 키르기즈스탄과 우즈베키스탄의 취약 지역 ... 기후 및 재해 회복력 강화",
            "사업예산 : 1,247,000,000원",
            "과업명 : 「모잠비크 마푸토 지능형교통시스템(ITS) 구축사업」타당성조사(F/S) 용역",
        ],
        normalized_values={
            "descending_budget_krw": [
                {"project": "KOICA 우즈베키스탄 열린 의정활동 상하원", "krw": 6758571493},
                {"project": "아시아물위원회 우즈벡-키르기즈스탄 스마트 관개시스템", "krw": 5031000000},
                {"project": "한국수출입은행 모잠비크 마푸토 ITS F/S", "krw": 1247000000},
            ]
        },
        confidence="high",
        raw_status="resolved",
        raw_notes="원문 3개 문서에서 대상국/분야/예산을 모두 확인.",
    ),
    "Q051": resolution(
        answer=(
            "부산국제영화제 사업은 BIFF·ACFM 공식 웹사이트, 모바일 앱, 참가·접수 시스템, 행사 지원시스템 등을 재개발해 "
            "참가자, 관리자, 사용자에게 편리한 온라인 행사·콘텐츠 서비스를 제공하고 브랜드 가치를 높이는 데 집중합니다. "
            "국립중앙의료원 사업은 응급의료 상황에서 병원 선정, 병원 간 전원, 재난 조정 업무를 처리하기 위한 중앙·광역 상황관리시스템과 "
            "IP 기반 콜센터를 구축해 응급환자 전원 지연과 상황관리 취약성을 개선하는 데 집중합니다."
        ),
        evidence_documents=[
            "(사)부산국제영화제_2024년 BIFF & ACFM 온라인서비스 재개발 및 행사지원시.hwp",
            "국립중앙의료원_(긴급)「2024년도 차세대 응급의료 상황관리시스템 구축.hwp",
        ],
        evidence_sentences=[
            "웹 표준, 웹 접근성 및 웹 UI에 대한 기능개선으로 사용자 중심의 웹서비스를 제공한다.",
            "BIFF, ACFM 각종 접수 및 참가 시스템을 ... 개선하여 참가자와 관리자의 편의성을 제고 한다.",
            "전국 중증응급질환자 병원 선정, 병원 간 전원 및 재난 조정 업무를 위한 IP기반 콜센터 구축",
            "중앙상황실의 전원접수 및 재난상황접수 처리를 위한 시스템 구축",
        ],
        normalized_values={},
        confidence="high",
        raw_status="resolved",
        raw_notes="원문 2개 문서에서 각 사업의 대비되는 개선 초점 확인.",
    ),
    "Q053": resolution(
        answer=(
            "세 사업은 각기 다른 사회·인프라 문제를 해결하기 위해 기획되었습니다. "
            "고려대학교 사업은 노후화되고 분산된 학사·포털 정보시스템을 통합해 정보서비스 품질과 대학 교육 시스템 경쟁력을 높이려는 사업이며 예산은 11,270,000,000원입니다. "
            "KOICA 사업은 우즈베키스탄 의회가 자체적으로 회의를 촬영·중계·저장하고 국민에게 실시간/VoD로 제공할 수 있는 국회 방송 인프라와 지역의회 연계 기반을 구축하려는 사업이며 예산은 6,758,571,493원입니다. "
            "아시아물위원회 사업은 키르기즈스탄과 우즈베키스탄의 홍수·가뭄 취약 지역에 스마트 양수·수문 기술을 도입해 기후 및 재해 회복력을 강화하려는 사업이며 예산은 5,031,000,000원입니다. "
            "세 사업의 예산 종합 금액은 23,059,571,493원입니다."
        ),
        evidence_documents=[
            "고려대학교_차세대 포털·학사 정보시스템 구축사업.pdf",
            "KOICA 전자조달_[긴급] [지문] [국제] 우즈베키스탄 열린 의정활동 상하원 .hwp",
            "사단법인아시아물위원회사무국_우즈벡-키르기즈스탄 기후변화대응 스.hwp",
        ],
        evidence_sentences=[
            "사업예산 : 11,270,000,000원 (V.A.T 포함, 3년 분할 지급)",
            "노후화된 학사 시스템을 기반으로 업무마다 분산된 정보화를 추진하고 있어, 시스템 통합에 대한 요구가 증가함",
            "집행 한도액 : 6,758,571,493원($5,198,901/1$=1,300원, 2024년 기준환율)",
            "수원기관은 자체적으로 회의를 촬영, 중계하고 이를 편집, 저장, VoD 서비스할 수 있는 물리적 인프라 ... 없는 상황임",
            "용역금액 : 5,031,000,000원",
            "스마트 양수 및 수문 설치를 통하여 ... 기후 및 재해 회복력 강화에 기여",
        ],
        normalized_values={
            "korea_univ_budget_krw": 11270000000,
            "koica_budget_krw": 6758571493,
            "awc_budget_krw": 5031000000,
            "total_budget_krw": 23059571493,
        },
        confidence="high",
        raw_status="resolved",
        raw_notes="질문 전제 금액과 원문 근거가 일치하도록 KOICA는 집행 한도액 기준으로 정리.",
    ),
    "Q054": resolution(
        answer=(
            "세 사업은 공통적으로 기존 업무시스템의 노후화·분산 운영·수작업/비효율을 줄이고, 업무 프로세스 표준화와 데이터 활용, 사용자 편의성을 높이는 방향의 전산화 사업입니다. "
            "한국가스공사는 ERP 기술지원 종료와 수작업·복잡도 문제를 해결하기 위해 SAP S/4 HANA 전환, 업무 프로세스 표준화, 데이터 기반 업무환경을 추진합니다. "
            "나노종합기술원은 FAB 공정장비의 실시간 모니터링, 설비 통신, 공정 데이터 수집·분석 체계를 구축합니다. 예산은 2,349,130,320원입니다. "
            "GKL은 그룹웨어·기록물관리·사내SNS·메신저 노후화를 개선하고 웹 기반 업무환경과 사용자 편의성을 높입니다. 원문 예산은 1,515,000천원이며 환산하면 1,515,000,000원입니다. "
            "다만 한국가스공사 원문에서는 사업 예산 금액이 직접 확인되지 않으므로, 세 기관 전체 중 최저 예산 기관을 확정할 수는 없습니다. 확인 가능한 예산만 비교하면 GKL이 나노종합기술원보다 낮습니다."
        ),
        evidence_documents=[
            "한국가스공사_[재공고]차세대 통합정보시스템(ERP) 구축.hwp",
            "나노종합기술원_스마트 팹 서비스 활용체계 구축관련 설비온라인 시스.hwp",
            "그랜드코리아레저(주)_2024년도 GKL 그룹웨어 시스템 구축 용역.hwp",
        ],
        evidence_sentences=[
            "기술지원 종료(‘27년)에 대비한 ERP 업그레이드",
            "‘09년 도입 이후 종합적인 개선 없이 단편적 수정으로 복잡도 증가 및 대사·검증 등 수작업에 따른 비효율 해소",
            "용역예산 : 2,349,130,320 원 (VAT포함)",
            "FAB내 공정장비의 실시간 모니터링을 위한 설비 통신 온라인 시스템 구축",
            "사업예산 : 1,515,000천원 (부가세 포함)",
            "그룹웨어 및 기록물관리, 사내SNS(별별얘기), 메신저 시스템 노후화 ... 개선 필요",
        ],
        normalized_values={
            "kogas_budget_krw": None,
            "nano_budget_krw": 2349130320,
            "gkl_budget_raw": "1,515,000천원",
            "gkl_budget_krw": 1515000000,
            "lowest_among_confirmed": "그랜드코리아레저(주)",
        },
        confidence="medium",
        raw_status="partial_grounded_refusal",
        raw_notes="목적 비교와 GKL/Nano 예산은 확인됐지만 한국가스공사 예산은 원문에서 직접 확인되지 않아 최저 기관 확정은 보류.",
    ),
    "Q072": resolution(
        answer=(
            "고려대학교 사업의 최종 사용자는 학생(졸업생 포함), 교직원, 연구원 등 교내 내부 구성원입니다. "
            "포털은 학생·교수 등 신분별/개인별 주요 정보와 학사·행정·연구 시스템 접근성을 제공하는 데 초점이 있습니다. "
            "반면 부산국제영화제 사업은 BIFF·ACFM 공식 웹사이트와 접수/참가 시스템, 행사 지원시스템을 이용하는 참가자, 관리자, 세일즈·바이어, 일반 사용자/방문자 등 대외 서비스 이용자를 중심으로 합니다. "
            "즉 고려대학교는 내부 구성원의 학사·행정 포털 이용 경험에, 부산국제영화제는 영화제·마켓 참가자와 외부 사용자의 온라인 서비스 경험에 더 초점을 둡니다."
        ),
        evidence_documents=[
            "고려대학교_차세대 포털·학사 정보시스템 구축사업.pdf",
            "(사)부산국제영화제_2024년 BIFF & ACFM 온라인서비스 재개발 및 행사지원시.hwp",
        ],
        evidence_sentences=[
            "학생(졸업생포함), 교직원, 연구원 등 내부 구성원 대상 포털",
            "학생/교수 등 신분별개인별 주요 정보 제공",
            "BIFF, ACFM 각종 접수 및 참가 시스템을 ... 참가자와 관리자의 편의성을 제고 한다.",
            "세일즈와 바이어 간의 정보를 실시간으로 공유",
        ],
        normalized_values={},
        confidence="high",
        raw_status="resolved",
        raw_notes="원문 2개 문서에서 최종 사용자 집단 근거 확인.",
    ),
    "Q145": resolution(
        answer=(
            "네, 포함된다고 볼 수 있습니다. 다만 별도 신규 구축 사업이라기보다는 산학협력단 정보시스템 운영·유지관리 범위 안에서 "
            "사용자 요구사항 반영, 연계시스템 추가 도입 시 지원 및 개발, 신규 또는 추가 개발된 부분의 운영/유지관리를 포함하는 형태입니다. "
            "근거 문서: 경희대학교_[입찰공고] 산학협력단 정보시스템 운영 용역업체 선정.hwp. "
            "근거 문장: \"사용자 요구사항에 대한 신속한 지원 및 시스템 반영\", \"정보시스템 개발/운영 관련 제반 업무\", "
            "\"연계시스템 추가 도입 시 시스템간 연동관련 지원 및 개발\", \"사업기간 내 산학협력단이 인정하여 신규 또는 추가 개발된 부분의 운영/유지관리\"."
        ),
        evidence_documents=["경희대학교_[입찰공고] 산학협력단 정보시스템 운영 용역업체 선정.hwp"],
        evidence_sentences=[
            "정보시스템 운영 효율화 및 안정적인 서비스 제공을 위한 시스템의 최적상태 유지",
            "사용자 요구사항에 대한 신속한 지원 및 시스템 반영",
            "정보시스템 개발/운영 관련 제반 업무",
            "연계시스템 추가 도입 시 시스템간 연동관련 지원 및 개발",
            "사업기간 내 산학협력단이 인정하여 신규 또는 추가 개발된 부분의 운영/유지관리",
        ],
        normalized_values={"new_or_additional_development_included": True},
        confidence="high",
        raw_status="resolved",
        raw_notes="기존 source_store가 다른 경희대 문서를 섞었지만, 원문 산학협력단 문서에서 직접 근거 확인.",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-labels", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-labels", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.input_labels)
    updated_rows: list[dict[str, Any]] = []
    applied: list[str] = []

    for row in rows:
        question_id = str(row.get("question_id") or "")
        new_row = dict(row)
        if question_id in RAW_RESOLUTIONS:
            patch = RAW_RESOLUTIONS[question_id]
            new_row.update(patch)
            applied.append(question_id)
        updated_rows.append(new_row)

    write_jsonl(args.output_labels, updated_rows)

    counts = {
        "input_rows": len(rows),
        "raw_resolved_rows": len(applied),
        "trainable_rows": sum(
            1
            for row in updated_rows
            if bool(row.get("trainable")) and not bool(row.get("needs_human_review"))
        ),
        "review_needed_rows": sum(
            1
            for row in updated_rows
            if not bool(row.get("trainable")) or bool(row.get("needs_human_review"))
        ),
    }

    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    report_lines = [
        "# 원본 문서 기반 PEFT 라벨 검수 결과",
        "",
        "## 요약",
        "",
        f"- 입력 라벨: `{args.input_labels}`",
        f"- 출력 라벨: `{args.output_labels}`",
        f"- 원본 검수로 보정한 문항: {counts['raw_resolved_rows']}개",
        f"- 최종 trainable 문항: {counts['trainable_rows']}개",
        f"- 추가 사람 검토 필요 문항: {counts['review_needed_rows']}개",
        "",
        "## 핵심 확인 사항",
        "",
        "- KOICA 방송시스템 문항은 기존 source_store의 `2,000,000,000원` 후보가 원문 직접 근거와 맞지 않았고, 원문 집행 한도액 `6,758,571,493원`을 기준으로 보정했습니다.",
        "- 인천광역시, 고려대학교, 국립중앙의료원, GKL 등은 원문에서 누락됐던 예산/목적/범위 근거를 확인해 비교형 답변을 보강했습니다.",
        "- 한국수자원공사와 한국가스공사는 원문에서 예산 금액이 직접 확인되지 않는 항목이 있어, 계산/최저 예산 판정은 확정하지 않는 답변으로 정리했습니다.",
        "- 경희대학교 산학협력단 문항은 기존 context에 다른 경희대 문서가 섞였지만, 원문 산학협력단 문서에서 신규/추가 개발 관련 운영·유지관리 근거를 확인했습니다.",
        "",
        "## 문항별 처리",
        "",
    ]
    for question_id in sorted(applied):
        patch = RAW_RESOLUTIONS[question_id]
        raw = patch["raw_original_review"]
        report_lines.extend(
            [
                f"### {question_id}",
                "",
                f"- 처리 상태: `{raw['status']}`",
                f"- 신뢰도: `{patch['confidence']}`",
                f"- 메모: {raw['notes']}",
                f"- 근거 문서: {', '.join(patch['evidence_documents'])}",
                "",
            ]
        )

    args.report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(f"[OK] wrote raw-resolved labels -> {args.output_labels}")
    print(f"[OK] wrote report -> {args.report_path}")
    print(json.dumps(counts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
