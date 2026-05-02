name: Auto Renew Server Script

on:
  repository_dispatch:
    types: [vps]
  workflow_dispatch:

jobs:
  run-renew:
    runs-on: ubuntu-latest
    timeout-minutes: 25

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.10"

      - name: Install System Dependencies
        run: |
          sudo apt-get update
          sudo apt-get install -y \
            xvfb ffmpeg unzip wget gnupg ca-certificates curl fontconfig \
            fonts-noto-cjk fonts-noto-color-emoji \
            fonts-wqy-zenhei fonts-wqy-microhei fonts-liberation

          wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub \
            | gpg --dearmor | sudo tee /usr/share/keyrings/google-linux.gpg >/dev/null
          echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-linux.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
            | sudo tee /etc/apt/sources.list.d/google-chrome.list
          sudo apt-get update
          sudo apt-get install -y google-chrome-stable

      - name: Install Python Dependencies
        run: |
          python -m pip install --upgrade pip
          pip install seleniumbase pyvirtualdisplay "requests[socks]" DrissionPage xvfbwrapper SpeechRecognition pydub

      - name: Prepare env
        env:
          VPS8_USERNAME: ${{ secrets.VPS8_USERNAME }}
          VPS8_PASSWORD: ${{ secrets.VPS8_PASSWORD }}
          VPS8_PROXY: ${{ secrets.VPS8_PROXY }}
          TG_BOT_TOKEN: ${{ secrets.TG_BOT_TOKEN }}
          TG_CHAT_ID: ${{ secrets.TG_CHAT_ID }}
        run: |
          test -f main.py

          [ -n "${VPS8_USERNAME:-}" ] || (echo "VPS8_USERNAME is empty" && exit 1)
          [ -n "${VPS8_PASSWORD:-}" ] || (echo "VPS8_PASSWORD is empty" && exit 1)

          # 同时写入两种变量名，兼容脚本大小写读取差异
          echo "VPS8_USERNAME=${VPS8_USERNAME}" >> "$GITHUB_ENV"
          echo "VPS8_PASSWORD=${VPS8_PASSWORD}" >> "$GITHUB_ENV"

          # 若脚本仍只支持 vps8_ACCOUNTS，这里自动拼接（不需要你手填）
          {
            echo "vps8_ACCOUNTS<<__EOF__"
            printf '%s' "${VPS8_USERNAME}:${VPS8_PASSWORD}"
            echo
            echo "__EOF__"
          } >> "$GITHUB_ENV"

          # 代理 & TG
          echo "PROXY=${VPS8_PROXY:-}" >> "$GITHUB_ENV"
          echo "TG_BOT_TOKEN=${TG_BOT_TOKEN:-}" >> "$GITHUB_ENV"
          echo "TG_TOKEN=${TG_BOT_TOKEN:-}" >> "$GITHUB_ENV"
          echo "TG_CHAT_ID=${TG_CHAT_ID:-}" >> "$GITHUB_ENV"

      - name: Run Script
        run: python main.py

      - name: Telegram notify on failure
        if: failure()
        env:
          TG_BOT_TOKEN: ${{ secrets.TG_BOT_TOKEN }}
          TG_CHAT_ID: ${{ secrets.TG_CHAT_ID }}
        run: |
          if [ -n "${TG_BOT_TOKEN:-}" ] && [ -n "${TG_CHAT_ID:-}" ]; then
            curl -sS "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
              -d chat_id="${TG_CHAT_ID}" \
              -d text="❌ VPS8 workflow failed: ${GITHUB_WORKFLOW} #${GITHUB_RUN_NUMBER}"
          fi

      - name: Upload Debug Artifacts
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: debug-screenshots
          path: |
            screenshots/**/*.png
            screenshots/**/*.html
            ./*.html
          if-no-files-found: ignore
          retention-days: 5
