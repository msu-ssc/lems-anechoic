"""Run the development web server with ``python -m msu_anechoic.web``."""

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "msu_anechoic.web.app:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
