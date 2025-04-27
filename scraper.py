#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
from bs4 import BeautifulSoup
import json
import datetime
import locale
import logging
import os
import time

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Configura o locale para Português do Brasil
try:
    locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8')
except locale.Error:
    logging.warning("Locale pt_BR.UTF-8 não encontrado. Usando locale padrão.")
    try:
        locale.setlocale(locale.LC_TIME, 'pt_BR')
    except locale.Error:
        logging.warning("Locale pt_BR também não encontrado. Usando locale padrão do sistema.")
        locale.setlocale(locale.LC_TIME, '') # Usa o locale padrão do sistema

# URLs
URL_FILTRO = "http://200.198.51.71/detec/filtro_boletim_es/filtro_boletim_es.php"

# --- Funções Auxiliares com Selenium ---

def setup_driver():
    """Configura e retorna uma instância do WebDriver do Chrome."""
    chrome_options = Options()
    chrome_options.add_argument("--headless") # Executar em modo headless (sem interface gráfica)
    chrome_options.add_argument("--no-sandbox") # Necessário para rodar como root/em container
    chrome_options.add_argument("--disable-dev-shm-usage") # Supera limitações de recursos
    chrome_options.add_argument("--window-size=1920,1080") # Definir tamanho da janela
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

    try:
        # Instala ou atualiza o ChromeDriver automaticamente
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        logging.info("WebDriver do Chrome configurado com sucesso.")
        return driver
    except Exception as e:
        logging.error(f"Erro ao configurar o WebDriver: {e}")
        # Tentar fallback para caminho padrão se webdriver-manager falhar
        try:
            logging.info("Tentando usar ChromeDriver padrão do sistema...")
            # Assumindo que o chromedriver está no PATH ou em /usr/bin/chromedriver
            service = ChromeService()
            driver = webdriver.Chrome(service=service, options=chrome_options)
            logging.info("WebDriver do Chrome (sistema) configurado com sucesso.")
            return driver
        except Exception as e2:
            logging.error(f"Erro ao configurar WebDriver do sistema também: {e2}")
            return None

def fetch_data_with_selenium():
    """Usa Selenium para navegar, preencher o formulário e obter o HTML da tabela."""
    driver = setup_driver()
    if not driver:
        return None

    try:
        logging.info(f"Acessando URL: {URL_FILTRO}")
        driver.get(URL_FILTRO)

        # Esperar o select de Mercado estar presente e visível
        wait = WebDriverWait(driver, 30) # Aumentar timeout
        mercado_select_element = wait.until(EC.visibility_of_element_located((By.NAME, "cd_mercado")))
        mercado_select = Select(mercado_select_element)

        # Selecionar "CEASA GRANDE VITÓRIA"
        logging.info("Selecionando Mercado: CEASA GRANDE VITÓRIA")
        mercado_select.select_by_visible_text("CEASA GRANDE VITÓRIA")

        # Esperar o select de Data ser populado (aguardar a segunda opção aparecer)
        data_select_locator = (By.XPATH, "//select[@name='dt_data']/option[position()=2]")
        wait.until(EC.presence_of_element_located(data_select_locator))
        logging.info("Select de data populado.")

        data_select_element = driver.find_element(By.NAME, "dt_data")
        data_select = Select(data_select_element)

        # Selecionar a primeira data disponível (índice 1, pois índice 0 é o placeholder)
        primeira_data_text = data_select.options[1].text.strip()
        logging.info(f"Selecionando Data: {primeira_data_text}")
        data_select.select_by_index(1)

        # Encontrar e clicar no botão "Ok"
        # Usar XPath para encontrar o link 'Ok' que provavelmente está associado ao formulário
        # Este XPath assume que é o segundo link 'Ok' na página, pode precisar de ajuste
        ok_button_locator = (By.XPATH, "(//a[contains(text(), 'Ok')])[2]")
        ok_button = wait.until(EC.element_to_be_clickable(ok_button_locator))
        logging.info("Clicando no botão OK.")
        # Usar JavaScript para clicar pode ser mais robusto
        driver.execute_script("arguments[0].click();", ok_button)

        # Esperar a página de resultados carregar (verificar pelo título)
        wait.until(EC.title_contains("Boletim Diário de Preços - Completo"))
        logging.info("Página de resultados carregada.")

        # Obter o HTML da página carregada
        html_content = driver.page_source
        return html_content

    except TimeoutException as e:
        logging.error(f"Timeout esperando elementos na página: {e}. Verifique os seletores ou a velocidade da rede.")
        # Capturar screenshot em caso de erro
        try:
            screenshot_path = f"/home/ubuntu/ceasa_scraper/error_screenshot_{int(time.time())}.png"
            driver.save_screenshot(screenshot_path)
            logging.info(f"Screenshot salvo em: {screenshot_path}")
        except Exception as se:
            logging.error(f"Falha ao salvar screenshot: {se}")
        return None
    except NoSuchElementException as e:
        logging.error(f"Elemento não encontrado: {e}")
        return None
    except Exception as e:
        logging.error(f"Erro inesperado durante a automação com Selenium: {e}")
        return None
    finally:
        if driver:
            driver.quit()
            logging.info("WebDriver fechado.")

# --- Funções de Parse e Save (Corrigidas) ---

def parse_data(html_content):
    """Analisa o HTML e extrai os dados da tabela de cotações."""
    if not html_content:
        return [], None

    soup = BeautifulSoup(html_content, 'html.parser')
    produtos = []

    # Encontrar a data da pesquisa
    data_pesquisa_str = "Data não encontrada"
    try:
        # Tentar extrair do cabeçalho que contém "Data Pesquisada:"
        # O texto exato pode variar, procurar por um padrão
        data_header = soup.find(lambda tag: tag.name == 'td' and 'Data Pesquisada:' in tag.get_text())
        if data_header:
            data_text = data_header.get_text(strip=True)
            data_pesquisa_str = data_text.split('Data Pesquisada:')[1].strip().split()[0] # Pega 'dd/mm/aaaa'
        else:
            # Fallback para o título da página
            title_tag = soup.find('title')
            if title_tag and 'Data Pesquisada:' in title_tag.text:
                data_pesquisa_str = title_tag.text.split('Data Pesquisada:')[1].strip()
            else:
                data_pesquisa_str = "Não localizada"
    except Exception as e:
        logging.warning(f"Erro ao extrair data da pesquisa: {e}. Usando '{data_pesquisa_str}'.")

    logging.info(f"Data da pesquisa extraída da página: {data_pesquisa_str}")

    # Encontrar a tabela correta (heurística baseada em cabeçalhos e número de linhas)
    target_table = None
    tables = soup.find_all('table')
    for table in tables:
        header_row = table.find('tr')
        if header_row and 'Produtos' in header_row.text and 'Embalagem' in header_row.text and 'MIN' in header_row.text:
            if len(table.find_all('tr')) > 10: # Assumindo que a tabela principal tem muitas linhas
                target_table = table
                logging.info("Tabela de produtos principal encontrada.")
                break

    if not target_table:
        logging.error("Tabela de produtos principal não encontrada no HTML.")
        # Salvar HTML para depuração
        try:
            with open("/home/ubuntu/ceasa_scraper/debug_page.html", "w", encoding='utf-8') as f:
                f.write(html_content)
            logging.info("HTML da página salvo em debug_page.html para análise.")
        except Exception as e:
            logging.error(f"Erro ao salvar HTML de depuração: {e}")
        return [], data_pesquisa_str

    rows = target_table.find_all('tr')
    header_skipped = False
    for row in rows:
        cols = row.find_all('td')

        # Pular cabeçalho principal da tabela
        if not header_skipped:
            if 'Produtos' in row.text and 'Embalagem' in row.text:
                header_skipped = True
            continue

        # Verificar se é uma linha de dados válida (ignorar subcabeçalhos/separadores)
        # Linhas de dados têm 6+ colunas, a primeira não está vazia e não é um subgrupo (sem <b>)
        if len(cols) >= 6 and cols[0].get_text(strip=True) and not cols[0].find('b'):
            try:
                produto_nome = cols[0].get_text(strip=True)
                unidade = cols[1].get_text(strip=True)
                # Colunas de preço: MIN, M.C., MAX (índices 2, 3, 4)
                # Remover pontos de milhar e substituir vírgula decimal por ponto
                preco_min_str = cols[2].get_text(strip=True).replace('.', '').replace(',', '.')
                preco_mc_str = cols[3].get_text(strip=True).replace('.', '').replace(',', '.') # M.C.
                preco_max_str = cols[4].get_text(strip=True).replace('.', '').replace(',', '.')

                # Tentar converter preços para float
                try:
                    preco_min = float(preco_min_str) if preco_min_str else None
                    preco_medio = float(preco_mc_str) if preco_mc_str else None
                    preco_max = float(preco_max_str) if preco_max_str else None
                except ValueError:
                    logging.warning(f"Não foi possível converter preços para o produto: {produto_nome}. Valores: Min='{preco_min_str}', Med='{preco_mc_str}', Max='{preco_max_str}'. Pulando linha.")
                    continue # Pula esta linha se a conversão falhar

                produtos.append({
                    "Produto": produto_nome,
                    "Unidade": unidade,
                    "Preco_Min": preco_min,
                    "Preco_Medio": preco_medio,
                    "Preco_Max": preco_max
                })
            except IndexError:
                logging.warning(f"Linha com formato inesperado (IndexError) encontrada e ignorada: {row.text.strip()}")
            except Exception as e:
                logging.error(f"Erro ao processar linha: {row.text.strip()} - {e}")
        # else: # Linha ignorada (cabeçalho, subgrupo, formato inválido)
            # logging.debug(f"Linha ignorada: {row.text.strip()}")

    logging.info(f"Total de {len(produtos)} produtos extraídos.")
    return produtos, data_pesquisa_str

def save_data(data, filename="data.json"):
    """Salva os dados extraídos em um arquivo JSON."""
    output_dir = os.path.dirname(filename)
    if output_dir and not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir)
            logging.info(f"Diretório criado: {output_dir}")
        except OSError as e:
            logging.error(f"Erro ao criar diretório {output_dir}: {e}")
            return # Não tentar salvar se não puder criar o diretório

    try:
        filepath = os.path.join(output_dir if output_dir else '.', os.path.basename(filename))
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logging.info(f"Dados salvos com sucesso em {filepath}")
    except IOError as e:
        logging.error(f"Erro ao salvar dados no arquivo {filepath}: {e}")
    except Exception as e:
        logging.error(f"Erro inesperado ao salvar dados: {e}")

# --- Função Principal ---

def main():
    """Função principal para orquestrar a busca e extração de dados com Selenium."""
    logging.info("Iniciando script de coleta de dados do CEASA-ES com Selenium.")
    output_filename = "/home/ubuntu/ceasa_scraper/ceasa_data.json"

    html_content = fetch_data_with_selenium()

    if not html_content:
        logging.error("Não foi possível obter o conteúdo HTML da página de cotações usando Selenium. Abortando.")
        error_data = {"data_pesquisa": "Erro na coleta", "produtos": []}
        save_data(error_data, filename=output_filename)
        return

    produtos, data_pesquisa = parse_data(html_content)

    if produtos:
        output_data = {
            "data_pesquisa": data_pesquisa,
            "produtos": produtos
        }
        save_data(output_data, filename=output_filename)
    else:
        logging.warning("Nenhum produto foi extraído. Verifique o HTML ou a lógica de parsing.")
        empty_data = {"data_pesquisa": data_pesquisa if data_pesquisa != "Data não encontrada" else "Sem dados", "produtos": []}
        save_data(empty_data, filename=output_filename)

    logging.info("Script de coleta de dados do CEASA-ES (Selenium) concluído.")

if __name__ == "__main__":
    main()


