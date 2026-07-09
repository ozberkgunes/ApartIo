import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8010))
    is_dev = os.environ.get("RENDER") is None
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1" if is_dev else "0.0.0.0",
        port=port,
        reload=is_dev,
    )
