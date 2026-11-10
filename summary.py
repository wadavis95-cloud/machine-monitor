
def summarize(lines: list[str]) -> list[str]:
    for line in lines:
        print(line.split())
       
summarize(["2026-11-05T07:17:00 press-01 temp 72.1",
          "2026-11-05T07:17:00 press-02 temp 80.0",
          "2026-11-05T07:17:00 press-02 vibration 1.0"])

    