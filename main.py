import uvicorn

if __name__ == "__main__":
    print("=======================================")
    print("🚀 Uruchamiam Multi-Agent Studio Web! 🚀")
    print("Otwórz przeglądarkę i wejdź pod adres:")
    print("👉 http://localhost:8000 👈")
    print("=======================================")
    uvicorn.run("backend.server:app", host="127.0.0.1", port=8000, reload=True)
