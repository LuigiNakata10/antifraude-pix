from datetime import timedelta


# Parâmetros do protótipo, não limiares validados nem usados universalmente
# pelos bancos. Todos os valores são em centavos. Cada um tem o porquê ao lado.

# Versão dos parâmetros e da ordem das regras: vai em todo `metadata`.
POLICY_VERSION = "pix-v1"

# R1 — conta pagadora nova.
# Menos de 7 dias completos entre a abertura e o Pix. Com exatamente 7 dias a
# conta deixa de ser nova. Sete dias dão tempo de a conta mostrar um padrão.
NEW_ACCOUNT_AGE = timedelta(days=7)
# R$ 1.000 em 24 h, contando o Pix atual: limita a exposição inicial e, por ser
# um acumulado, impede contornar o teto fracionando em vários Pix.
NEW_ACCOUNT_LIMIT = 1000 * 100

# R2 — teto geral.
# R$ 10.000 em 24 h numa janela móvel: exposição máxima simples e resistente à
# fragmentação. Só Pix `approved` consomem o limite.
DAILY_WINDOW = timedelta(hours=24)
DAILY_LIMIT = 10000 * 100

# R3 — frequência.
# O terceiro pedido distinto em 2 minutos pede 2FA, com qualquer valor e
# qualquer destinatário: uma rajada concentrada pede confirmação de identidade
# sem rejeitar só por quantidade. Conta qualquer resultado, não reenvios.
FREQUENCY_WINDOW = timedelta(minutes=2)
FREQUENCY_THRESHOLD = 3

# R4 — dispositivo novo e valor elevado.
# Pix de R$ 5.000 ou mais num aparelho que ainda não é conhecido pede 2FA:
# falta de familiaridade do acesso somada a uma exposição relevante.
HIGH_AMOUNT = 5000 * 100
# O aparelho só é conhecido 24 h depois da PRIMEIRA aprovação, e aprovações
# posteriores não reiniciam a espera: evita que um Pix pequeno aprovado
# dispense o 2FA de imediato, sem prolongar a espera de quem usa a conta todo dia.
DEVICE_WAIT = timedelta(hours=24)

# ---------------------------------------------------------------------------
# Módulo de conta laranja: o motor primeiro classifica a conta e depois decide
# o ato. Os valores também são parâmetros do protótipo, não limiares validados.
# ---------------------------------------------------------------------------

# E1 — marcação no DICT (janela de 90 dias, `d90`): pelo menos uma conta laranja
# ou golpista marcada, ou o titular marcado por 2 ou mais instituições. Uma
# marcação de outra instituição é a semente mais forte que o motor tem: ele
# deixa de depender só do que viu passar por ele.
E1_REPORTERS_THRESHOLD = 2

# E4 — notificações de infração abertas contra a conta, no DICT: 2 ou mais.
# Uma só pode ser uma disputa; duas já são um padrão. E4 sozinha é só `suspeita`.
E4_OPEN_REPORTS_THRESHOLD = 2

# Janelas das evidências locais (E2, E3 e E5). Quando a janela passa, a
# evidência some e o estado cai sozinho: não existe marcação local permanente.
E2_WINDOW = timedelta(days=30)
E3_WINDOW = timedelta(hours=1)
E5_WINDOW = timedelta(hours=24)

# Gasto típico — o padrão de quem usa a conta para a própria vida: até R$ 1.000
# para um titular que o pagador já conhecia, ou para um CNPJ com conta de 90
# dias ou mais. O teto e a exigência de CNPJ antigo existem para o repasse não
# se disfarçar de "gasto" numa empresa de fachada recém-aberta.
TYPICAL_SPEND_LIMIT = 1000 * 100
ESTABLISHED_CNPJ_AGE = timedelta(days=90)
