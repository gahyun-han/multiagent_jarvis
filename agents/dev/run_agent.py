"""
RunAgent — executes external project scripts on request.
Supports: "TrendNotifier 실행해줘", "PaperRadar 돌려줘" etc.
"""
import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXTERNAL_DIR = PROJECT_ROOT / "external"
HOME = Path.home()

# 프로젝트별 진입점 설정 (없으면 main.py 자동 탐색)
_ENTRY_POINTS: dict[str, str] = {
    "TrendNotifier": "main.py",
    "PaperRadar": "main.py",
    "Stock-agent": "main.py",
    "techTerminologyRadar": "main.py",
    "UserCustomStockinfo_agent": "main.py",
}

_PROJECT_ALIASES: dict[str, str] = {
    "트렌드노티파이어": "TrendNotifier",
    "트렌드": "TrendNotifier",
    "trendnotifier": "TrendNotifier",
    "페이퍼레이더": "PaperRadar",
    "논문레이더": "PaperRadar",
    "paperradar": "PaperRadar",
    "주식": "Stock-agent",
    "stock": "Stock-agent",
    "itterminology": "techTerminologyRadar",
    "it용어": "techTerminologyRadar",
    "용어레이더": "techTerminologyRadar",
    "terminology": "techTerminologyRadar",
    "techterminologyradar": "techTerminologyRadar",
}


class RunAgent:
    async def handle(self, intent) -> str:
        message = intent.raw_message
        project_dir, entry = self._resolve_project(message)

        if project_dir is None:
            available = ", ".join(p.name for p in EXTERNAL_DIR.iterdir() if p.is_dir())
            return f"⚠️ 실행할 프로젝트를 찾지 못했습니다.\n실행 가능한 프로젝트: {available}"

        script = project_dir / entry
        if not script.exists():
            return f"⚠️ 진입점 없음: {script}"

        logger.info(f"RunAgent: {script}")
        return self._run(project_dir, script)

    def _resolve_project(self, message: str) -> tuple[Path | None, str]:
        msg_lower = message.lower()

        # 1. 별칭 매핑
        for alias, name in _PROJECT_ALIASES.items():
            if alias in msg_lower:
                return self._find_dir(name)

        # 2. 프로젝트 이름 직접 매칭
        for proj_dir in EXTERNAL_DIR.iterdir():
            if proj_dir.name.lower() in msg_lower:
                entry = _ENTRY_POINTS.get(proj_dir.name, "main.py")
                return proj_dir.resolve(), entry

        # 3. 메시지 내 경로 패턴 탐색
        m = re.search(r"([\w\-]+)/(\w+\.py)", message)
        if m:
            candidate = EXTERNAL_DIR / m.group(1)
            if candidate.exists():
                return candidate.resolve(), m.group(2)

        return None, "main.py"

    def _find_dir(self, name: str) -> tuple[Path | None, str]:
        p = EXTERNAL_DIR / name
        if p.exists():
            return p.resolve(), _ENTRY_POINTS.get(name, "main.py")
        return None, "main.py"

    def _find_python(self, project_dir: Path) -> str:
        """프로젝트 전용 .venv가 있으면 그걸 사용, 없으면 Jarvis venv."""
        for candidate in [
            project_dir / ".venv" / "bin" / "python",
            project_dir / "venv" / "bin" / "python",
        ]:
            if candidate.exists():
                return str(candidate)
        return "/Users/hanga/venv/bin/python3.14"

    def _run(self, project_dir: Path, script: Path) -> str:
        python = self._find_python(project_dir)
        try:
            result = subprocess.run(
                [python, str(script)],
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = (result.stdout + result.stderr).strip()
            status = "✅ 실행 완료" if result.returncode == 0 else f"⚠️ 종료 코드 {result.returncode}"
            tail = f"\n```\n{output[-600:]}\n```" if output else ""
            return f"{status}: `{script.name}` ({project_dir.name}){tail}"
        except subprocess.TimeoutExpired:
            return f"⏰ 실행 시간 초과 (120s): {script.name}"
        except Exception as e:
            return f"❌ 실행 오류: {e}"
