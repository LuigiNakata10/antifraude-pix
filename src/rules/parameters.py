from datetime import timedelta


# Parâmetros do protótipo, não limiares validados nem usados universalmente
# pelos bancos. Todos os valores são em centavos. Cada um tem o porquê ao lado.

# Versão dos parâmetros e da ordem das regras: vai em todo `metadata`.
POLICY_VERSION = "pix-v1.3"

# R1 — conta pagadora nova.
# Menos de 7 dias completos entre a abertura e o Pix. Com exatamente 7 dias a
# conta deixa de ser nova. Sete dias dão tempo de a conta mostrar um padrão.
NEW_ACCOUNT_AGE = timedelta(days=7)
# R$ 1.000 em 24 h, contando o Pix atual: limita a exposição inicial e, por ser
# um acumulado, impede contornar o teto fracionando em vários Pix.
NEW_ACCOUNT_LIMIT = 1000 * 100

# R2 — teto geral.
# R$ 20.000 em 24 h numa janela móvel: exposição máxima simples e resistente à
# fragmentação. Só Pix `approved` consomem o limite.
DAILY_WINDOW = timedelta(hours=24)
DAILY_LIMIT = 20000 * 100

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

# R5 — desvio do valor habitual da conta pagadora.
# A média usa todos os Pix enviados e aprovados observados até a transação,
# sem incluir o pedido atual. A referência é o maior entre a média e R$ 500:
# um pagamento pequeno não desliga a proteção ao derrubar a média abaixo do piso.
# Um Pix acima de 10 vezes a referência pede 2FA, inclusive em aparelho conhecido.
# Sem aprovações anteriores, a regra não atua. O limite é estrito (>).
ACCOUNT_AVERAGE_REFERENCE_FLOOR = 500 * 100
ACCOUNT_AVERAGE_MULTIPLIER = 10

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

# E2 — o dinheiro e o aparelho de uma conta marcada no DICT (E1), 30 dias.
# Só E1 propaga, e só um salto: a suspeita não anda em círculo nem em cadeia.
# MAIS de 50% do que a conta recebeu em 30 dias veio de contas com E1 (a
# proporção protege quem recebeu de boa-fé: R$ 1 mandado de propósito não pesa),
# ou ela usou o mesmo aparelho de uma conta com E1.
E2_SHARE_PERCENT = 50
# Trava de reputação: E2 só vale para conta com menos de 90 dias OU menos de 10
# contrapartes. Uma padaria antiga, com muitos clientes, não ganha E2.
E2_REPUTATION_AGE = timedelta(days=90)
E2_REPUTATION_COUNTERPARTIES = 10

# E3 — muitos titulares enviando, pelo menos três estreantes, na última hora:
# o formato de uma conta de passagem. Empresa recebe de muita gente por
# natureza, então o limiar do CNPJ é bem maior.
E3_HOLDERS = 5
E3_FIRST_TIME_HOLDERS = 3
E3_HOLDERS_COMPANY = 30
E3_FIRST_TIME_HOLDERS_COMPANY = 3

# E5 — conta com menos de 7 dias recebendo volume alto de vários titulares:
# mais de R$ 5.000 em 24 h, de 3 ou mais titulares.
E5_ACCOUNT_AGE = timedelta(days=7)
E5_AMOUNT = 5000 * 100
E5_HOLDERS = 3

# Repasse — o dinheiro sai logo depois de entrar, que é o que define uma conta
# de passagem: a conta recebeu pelo menos R$ 1.000 aprovados na última hora, este
# Pix leva o total enviado na hora a 50% ou mais disso, e o destino é pessoa
# física ou CNPJ com conta de menos de 90 dias (o mesmo ESTABLISHED_CNPJ_AGE).
REPASSE_WINDOW = timedelta(hours=1)
REPASSE_MIN_RECEIVED = 1000 * 100
REPASSE_SHARE_PERCENT = 50

# Janelas das evidências locais (E2, E3 e E5). Quando a janela passa, a
# evidência some e o estado cai sozinho: não existe marcação local permanente.
E2_WINDOW = timedelta(days=30)
E3_WINDOW = timedelta(hours=1)
E5_WINDOW = timedelta(hours=24)

# Gasto típico — o padrão de quem usa a conta para a própria vida: até R$ 1.000
# para um titular que o pagador já conhecia, ou para um CNPJ com conta de 90
# dias ou mais. O teto e a exigência de CNPJ antigo existem para o repasse não
# se disfarçar de "gasto" numa empresa de fachada recém-aberta. Repasse é avaliado primeiro.
TYPICAL_SPEND_LIMIT = 1000 * 100
ESTABLISHED_CNPJ_AGE = timedelta(days=90)

# O mínimo técnico de transaction_date precisa comportar todos os recuos,
# sem ultrapassar datetime.min. Idades são diferenças, não subtrações de janela.
MAX_HISTORY_WINDOW = max(DAILY_WINDOW, FREQUENCY_WINDOW, E2_WINDOW, E3_WINDOW, E5_WINDOW, REPASSE_WINDOW)
