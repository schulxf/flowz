# FreeFlow Windows MVP

FreeFlow Windows MVP e um ditado por voz para Windows: segure `Ctrl + Windows`
para gravar, solte as teclas para transcrever e o texto sera colado
automaticamente no aplicativo que estiver em foco.

Este repositorio contem uma versao Windows-first do FreeFlow, escrita em Python,
com foco em rodar localmente com poucas dependencias. O app usa `ffmpeg` para
capturar o microfone via DirectShow, `curl.exe` para chamadas HTTP por padrao e
um endpoint compativel com OpenAI em `/audio/transcriptions`.

Repositorio remoto:

```text
https://github.com/schulxf/freeflow_ws.git
```

## Visao geral

- Atalho global: `Ctrl + Windows`.
- Fluxo: grava audio, envia para transcricao, cola o texto com `Ctrl+V`.
- Provider padrao: Groq, usando `https://api.groq.com/openai/v1`.
- Modelo padrao: `whisper-large-v3`.
- Sem dependencias Python de runtime alem da biblioteca padrao.
- Interface discreta com indicador visual sempre ativo.
- Suporte a execucao em terminal, em background com `pythonw.exe` ou como `.exe`.

## Requisitos

- Windows 10 ou Windows 11.
- Python 3.10 ou superior instalado e disponivel no PATH.
- `ffmpeg` instalado e disponivel no PATH.
- `curl.exe` disponivel. Em instalacoes modernas do Windows ele geralmente ja
  vem instalado.
- Uma API key de um provider compativel com a API da OpenAI. O padrao do projeto
  e Groq.

Verifique as ferramentas:

```powershell
python --version
ffmpeg -version
curl.exe --version
```

Se `ffmpeg` nao estiver instalado, uma opcao e usar `winget`:

```powershell
winget install Gyan.FFmpeg
```

Depois de instalar, feche e abra o terminal novamente para o PATH ser recarregado.

## Arquivos principais

```text
freeflow_win.py              Codigo principal do app
FreeFlowWin.bat              Executa o app no terminal
FreeFlowWin-Background.bat   Executa em background com pythonw.exe
FreeFlowWin-Stop.bat         Envia sinal para parar uma instancia em background
FreeFlowWin.pyw              Entrada para execucao sem console
build-exe.ps1                Gera o executavel com PyInstaller
config.example.json          Exemplo de configuracao
README.md                    Documentacao do projeto
```

Os diretorios `build/` e `dist/` sao gerados pelo PyInstaller e nao devem ser
versionados. O executavel gerado fica em `dist\FreeFlowWin.exe`.

## Instalacao para desenvolvimento

Clone o repositorio:

```powershell
git clone https://github.com/schulxf/freeflow_ws.git
cd freeflow_ws
```

Opcional, mas recomendado: crie um ambiente virtual.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

O app em si nao precisa instalar pacotes Python para rodar. Para gerar `.exe`, o
script `build-exe.ps1` instala `pyinstaller` no Python ativo.

## Configuracao inicial

Execute o setup:

```powershell
.\FreeFlowWin.bat --setup
```

O setup pergunta:

- API key.
- Base URL do provider.
- Modelo de transcricao.
- Microfone detectado pelo `ffmpeg`.

A configuracao e salva fora do repositorio, em:

```powershell
.\FreeFlowWin.bat --config-path
```

Normalmente o caminho sera:

```text
%APPDATA%\FreeFlowWin\config.json
```

Tambem e possivel configurar a chave por variavel de ambiente antes de iniciar:

```powershell
$env:FREEFLOW_API_KEY = "sua_api_key"
.\FreeFlowWin.bat
```

As variaveis aceitas para chave sao:

- `FREEFLOW_API_KEY`
- `GROQ_API_KEY`
- `OPENAI_API_KEY`

Para trocar a URL base sem editar o JSON:

```powershell
$env:FREEFLOW_BASE_URL = "https://api.groq.com/openai/v1"
```

## Configuracao disponivel

Exemplo base em `config.example.json`:

```json
{
  "api_key": "",
  "base_url": "https://api.groq.com/openai/v1",
  "transcription_model": "whisper-large-v3",
  "language": "",
  "request_timeout_seconds": 60,
  "http_transport": "curl",
  "curl_path": "curl.exe",
  "ffmpeg_path": "ffmpeg",
  "ffmpeg_device": "",
  "post_process": false,
  "post_process_model": "openai/gpt-oss-20b",
  "paste_result": true,
  "append_space_after_sentence": true,
  "preserve_text_clipboard": true,
  "visual_indicator": true,
  "visual_indicator_success_seconds": 1.1
}
```

Campos principais:

| Campo | Descricao |
| --- | --- |
| `api_key` | Chave do provider. Prefira salvar via `--setup` ou variavel de ambiente. |
| `base_url` | URL base compativel com OpenAI. Padrao: Groq. |
| `transcription_model` | Modelo usado em `/audio/transcriptions`. |
| `language` | Idioma opcional da transcricao. Deixe vazio para autodeteccao. |
| `request_timeout_seconds` | Timeout das chamadas HTTP. |
| `http_transport` | `curl` por padrao. Pode ser alterado para `urllib`. |
| `curl_path` | Caminho do `curl.exe`. |
| `ffmpeg_path` | Caminho do `ffmpeg`. |
| `ffmpeg_device` | Nome do microfone DirectShow. Vazio usa o primeiro detectado. |
| `post_process` | Ativa limpeza do texto via `/chat/completions`. |
| `post_process_model` | Modelo usado para limpeza quando `post_process` esta ativo. |
| `paste_result` | Se `true`, cola automaticamente. Se `false`, apenas copia para clipboard. |
| `append_space_after_sentence` | Adiciona espaco apos frases terminadas com `.`, `!` ou `?`. |
| `preserve_text_clipboard` | Tenta restaurar o texto anterior do clipboard apos colar. |
| `visual_indicator` | Mostra/oculta o indicador visual. |
| `visual_indicator_success_seconds` | Tempo de feedback visual apos sucesso. |

## Como usar

Rode no terminal:

```powershell
.\FreeFlowWin.bat
```

Depois:

1. Clique no campo de texto onde voce quer ditar.
2. Segure `Ctrl + Windows`.
3. Fale normalmente.
4. Solte as duas teclas.
5. Aguarde a transcricao ser colada automaticamente.

Mantenha o terminal aberto enquanto o app estiver rodando. Ele mostra logs basicos
de estado, microfone e erros.

## Rodar sem terminal

Para iniciar em background:

```powershell
.\FreeFlowWin-Background.bat
```

Ou de dois cliques em:

```text
FreeFlowWin.pyw
```

Para parar a instancia em background:

```powershell
.\FreeFlowWin-Stop.bat
```

## Comandos de diagnostico

Listar microfones detectados pelo `ffmpeg`:

```powershell
.\FreeFlowWin.bat --list-devices
```

Gravar um WAV local por 3 segundos, sem chamar a API:

```powershell
.\FreeFlowWin.bat --test-record 3
```

Testar API key e conectividade com o provider:

```powershell
.\FreeFlowWin.bat --test-api
```

Testar colagem com `Ctrl+V` sem transcrever:

```powershell
.\FreeFlowWin.bat --test-paste
```

Visualizar estados do indicador visual:

```powershell
.\FreeFlowWin.bat --test-overlay
```

Mostrar caminho da configuracao:

```powershell
.\FreeFlowWin.bat --config-path
```

Parar uma instancia em execucao:

```powershell
.\FreeFlowWin.bat --stop
```

## Gerar executavel

Execute:

```powershell
.\build-exe.ps1
```

O script instala `pyinstaller` no Python ativo e gera:

```text
dist\FreeFlowWin.exe
```

Para rodar:

```powershell
.\dist\FreeFlowWin.exe
```

Para parar uma instancia do executavel:

```powershell
.\dist\FreeFlowWin.exe --stop
```

Recomendacao: nao versione `dist\FreeFlowWin.exe` no Git. Para distribuir binario,
publique o executavel em uma Release do GitHub.

## Logs e erros

O app grava logs em:

```text
%APPDATA%\FreeFlowWin\freeflow.log
```

Quando ocorre uma falha com stack trace, os detalhes sao gravados em:

```text
%APPDATA%\FreeFlowWin\last-error.txt
```

## Solucao de problemas

### `ffmpeg was not found on PATH`

Instale o `ffmpeg` e confirme:

```powershell
ffmpeg -version
```

Se preferir nao alterar PATH, edite `ffmpeg_path` no `config.json` com o caminho
absoluto do executavel.

### Nenhum microfone aparece

Rode:

```powershell
.\FreeFlowWin.bat --list-devices
```

Verifique permissoes de microfone do Windows e se outro app consegue capturar
audio. Depois rode `--setup` novamente para selecionar o dispositivo correto.

### A transcricao funciona, mas nao cola

Teste a colagem:

```powershell
.\FreeFlowWin.bat --test-paste
```

Alguns apps com permissao elevada podem bloquear entrada simulada enviada por um
processo sem elevacao. Nesse caso, rode o FreeFlowWin com a mesma permissao do
app de destino.

### API retorna erro HTTP

Rode:

```powershell
.\FreeFlowWin.bat --test-api
```

Confira `api_key`, `base_url`, `transcription_model` e se o provider aceita o
endpoint `/audio/transcriptions`.

### O atalho abre o menu do Windows

O app tenta suprimir as teclas durante `Ctrl + Windows`. Se o menu aparecer,
garanta que so existe uma instancia rodando:

```powershell
.\FreeFlowWin.bat --stop
.\FreeFlowWin.bat
```

## Preparar e publicar no GitHub

Este repositorio foi preparado para usar:

```text
https://github.com/schulxf/freeflow_ws.git
```

Fluxo recomendado:

```powershell
git init
git branch -M main
git remote add origin https://github.com/schulxf/freeflow_ws.git
git add .
git commit -m "Initial FreeFlow Windows MVP"
git push -u origin main
```

Se o remoto ja existir localmente:

```powershell
git remote set-url origin https://github.com/schulxf/freeflow_ws.git
```

Antes de commitar, confirme que arquivos sensiveis nao entraram no stage:

```powershell
git status --short
```

Nao versione:

- `config.json`
- `.env`
- chaves de API
- `build/`
- `dist/`
- logs locais

## Licenca

Defina a licenca do projeto antes de distribuir publicamente. Enquanto nao houver
um arquivo `LICENSE`, todos os direitos ficam reservados por padrao.
