# run_server.py
import os
import asyncio

# 1) Windows에서는 제일 먼저 Selector 정책으로 바꿉니다.
if os.name == "nt":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

# 2) 그런 다음에 uvicorn을 import 합니다.
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "api.app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,         # 필요시 True
        loop="asyncio",       # 명시
        http="h11",           # 윈도우에서 안정적
        lifespan="on",        # 문제 있으면 "off" 로 바꿔보세요
    )
