import json
import requests
from web3 import Web3
from eth_account import Account
from web3.middleware import geth_poa_middleware
import time
import os
from telegram import Update
from telegram.ext import CallbackContext

class ClankerSniper:
    def __init__(self, rpc_url, private_key):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        self.account = Account.from_key(private_key)
        self.address = self.account.address

        # Adresses des contrats sur Base
        self.WETH_ADDRESS = "0x4200000000000000000000000000000000000006"
        self.UNISWAP_V3_ROUTER = "0x2626664c2603336E57B271c5C0b26F421741e481"  # Routeur officiel Uniswap V3 sur Base
        self.UNISWAP_V3_QUOTER = "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"

        # ABI minimal pour les contrats
        self.WETH_ABI = [
            {
                "constant": False,
                "inputs": [{"name": "wad", "type": "uint256"}],
                "name": "withdraw",
                "outputs": [],
                "payable": False,
                "stateMutability": "nonpayable",
                "type": "function"
            },
            {
                "constant": False,
                "inputs": [{"name": "guy", "type": "address"}, {"name": "wad", "type": "uint256"}],
                "name": "approve",
                "outputs": [{"name": "", "type": "bool"}],
                "payable": False,
                "stateMutability": "nonpayable",
                "type": "function"
            }
        ]

        self.ROUTER_ABI = [
            {
                "inputs": [
                    {
                        "components": [
                            {"internalType": "address", "name": "tokenIn", "type": "address"},
                            {"internalType": "address", "name": "tokenOut", "type": "address"},
                            {"internalType": "uint24", "name": "fee", "type": "uint24"},
                            {"internalType": "address", "name": "recipient", "type": "address"},
                            {"internalType": "uint256", "name": "deadline", "type": "uint256"},
                            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                            {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"},
                            {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}
                        ],
                        "internalType": "struct ISwapRouter.ExactInputSingleParams",
                        "name": "params",
                        "type": "tuple"
                    }
                ],
                "name": "exactInputSingle",
                "outputs": [
                    {"internalType": "uint256", "name": "amountOut", "type": "uint256"}
                ],
                "stateMutability": "payable",
                "type": "function"
            }
        ]

        # Initialisation des contrats
        self.weth_contract = self.w3.eth.contract(address=self.WETH_ADDRESS, abi=self.WETH_ABI)
        self.router_contract = self.w3.eth.contract(address=self.UNISWAP_V3_ROUTER, abi=self.ROUTER_ABI)

    def get_clanker_tokens(self, fid=None):
        """Récupère les tokens Clanker, optionnellement filtrés par FID"""
        url = "https://api.clanker.xyz/tokens"
        if fid:
            url += f"?fid={fid}"
        
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        return None

    def get_token_info(self, token_address):
        """Récupère les informations détaillées d'un token"""
        url = f"https://api.clanker.xyz/tokens/{token_address}"
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        return None

    def approve_weth(self, amount):
        """Approuve le router Uniswap pour utiliser les WETH"""
        try:
            tx = self.weth_contract.functions.approve(
                self.UNISWAP_V3_ROUTER,
                amount
            ).build_transaction({
                'from': self.address,
                'gas': 100000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(self.address),
            })
            
            signed_tx = self.w3.eth.account.sign_transaction(tx, self.account.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            return self.w3.eth.wait_for_transaction_receipt(tx_hash)
        except Exception as e:
            print(f"Erreur lors de l'approbation WETH: {str(e)}")
            return None

    def execute_swap(self, token_address, amount_in, gas_price=None):
        """Exécute un swap WETH -> Token via Uniswap V3"""
        try:
            # Paramètres du swap
            params = {
                'tokenIn': self.WETH_ADDRESS,
                'tokenOut': token_address,
                'fee': 3000,  # 0.3% fee tier
                'amountIn': amount_in,
                'amountOutMinimum': 0,  # Attention: Risque de slippage
                'sqrtPriceLimitX96': 0,
                'recipient': self.address,
                'deadline': self.w3.eth.get_block('latest').timestamp + 300  # 5 minutes
            }

            # Construction de la transaction
            tx = self.router_contract.functions.exactInputSingle(params).build_transaction({
                'from': self.address,
                'gas': 300000,
                'gasPrice': gas_price or self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(self.address),
            })

            # Signature et envoi de la transaction
            signed_tx = self.w3.eth.account.sign_transaction(tx, self.account.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            return self.w3.eth.wait_for_transaction_receipt(tx_hash)

        except Exception as e:
            print(f"Erreur lors du swap: {str(e)}")
            return None

    def monitor_new_tokens(self, target_fid, callback):
        """Monitore les nouveaux tokens pour un FID spécifique"""
        last_checked_block = self.w3.eth.block_number
        
        while True:
            current_block = self.w3.eth.block_number
            if current_block > last_checked_block:
                tokens = self.get_clanker_tokens(target_fid)
                if tokens:
                    for token in tokens:
                        # Vérifier si le token est nouveau
                        if token.get('blockNumber', 0) > last_checked_block:
                            callback(token)
                last_checked_block = current_block 

    def get_amount_out(self, weth_address, token_address, amount_in_wei, slippage):
        """Utilise le Quoter Uniswap V3 pour estimer le minOut avec slippage"""
        try:
            quoter_abi = [{
                "inputs": [
                    {"internalType": "address", "name": "tokenIn", "type": "address"},
                    {"internalType": "address", "name": "tokenOut", "type": "address"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"},
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}
                ],
                "name": "quoteExactInputSingle",
                "outputs": [
                    {"internalType": "uint256", "name": "amountOut", "type": "uint256"}
                ],
                "stateMutability": "view",
                "type": "function"
            }]
            quoter = self.w3.eth.contract(address=self.UNISWAP_V3_QUOTER, abi=quoter_abi)
            amount_out = quoter.functions.quoteExactInputSingle(
                weth_address,
                token_address,
                3000,
                amount_in_wei,
                0
            ).call()
            min_out = int(amount_out * (1 - slippage / 100))
            return min_out
        except Exception as e:
            print(f"Erreur get_amount_out: {str(e)}")
            return 0

    def swap_weth_for_token(self, router_address, weth_address, token_address, amount_in_wei, min_out=0):
        """Effectue un swap WETH -> token via Uniswap v3 (exactInputSingle), retourne le hash de la transaction."""
        try:
            # Utilise toujours le routeur officiel
            router = self.w3.eth.contract(address=self.UNISWAP_V3_ROUTER, abi=self.ROUTER_ABI)
            
            # Vérification du solde WETH
            weth_balance = self.w3.eth.get_balance(self.address)
            if weth_balance < amount_in_wei:
                raise Exception(f"Solde WETH insuffisant: {Web3.from_wei(weth_balance, 'ether')} WETH < {Web3.from_wei(amount_in_wei, 'ether')} WETH requis")

            # Approve WETH if needed
            approve_tx = self.approve_weth(amount_in_wei)
            if not approve_tx:
                raise Exception("Échec de l'approbation WETH")

            params = {
                'tokenIn': weth_address,
                'tokenOut': token_address,  # le token cible, PAS la pool
                'fee': 3000,
                'recipient': self.address,
                'deadline': self.w3.eth.get_block('latest').timestamp + 300,
                'amountIn': amount_in_wei,
                'amountOutMinimum': min_out,
                'sqrtPriceLimitX96': 0
            }

            # Simulation de la transaction avant envoi
            try:
                router.functions.exactInputSingle(params).call({
                    'from': self.address,
                    'value': 0
                })
            except Exception as e:
                raise Exception(f"Échec de la simulation du swap: {str(e)}")

            tx = router.functions.exactInputSingle(params).build_transaction({
                'from': self.address,
                'gas': 300000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(self.address),
            })

            signed_tx = self.w3.eth.account.sign_transaction(tx, self.account.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            # Attente de la confirmation et vérification du statut
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
            if receipt['status'] == 0:
                # Récupération de la raison de l'échec
                try:
                    tx = self.w3.eth.get_transaction(tx_hash)
                    result = self.w3.eth.call(tx, block_identifier=receipt['blockNumber']-1)
                    raise Exception(f"Transaction échouée: {result}")
                except Exception as e:
                    raise Exception(f"Transaction échouée: {str(e)}")
            
            return tx_hash.hex()
        except Exception as e:
            print(f"Erreur détaillée lors du swap_weth_for_token: {str(e)}")
            return None

    def swap_eth_for_token(self, token_address, amount_in_wei, min_out=0):
        """
        Effectue un swap ETH natif -> token via Uniswap V3 (exactInputSingle).
        Vérifie d'abord la liquidité des pools et utilise le meilleur fee tier.
        """
        try:
            # 1. Vérification du solde ETH
            eth_balance = self.w3.eth.get_balance(self.address)
            if eth_balance < amount_in_wei:
                raise Exception(f"Solde ETH insuffisant: {Web3.from_wei(eth_balance, 'ether')} ETH < {Web3.from_wei(amount_in_wei, 'ether')} ETH requis")

            # 2. Vérification des pools pour chaque fee tier
            fee_tiers = [500, 3000, 10000]  # 0.05%, 0.3%, 1%
            best_pool = None
            best_liquidity = 0

            factory_contract = self.w3.eth.contract(
                address="0x33128a8fC17869897dcE68Ed026d694621f6FDfD",  # Uniswap V3 Factory
                abi=[{
                    "inputs": [
                        {"internalType": "address", "name": "tokenA", "type": "address"},
                        {"internalType": "address", "name": "tokenB", "type": "address"},
                        {"internalType": "uint24", "name": "fee", "type": "uint24"}
                    ],
                    "name": "getPool",
                    "outputs": [{"internalType": "address", "name": "", "type": "address"}],
                    "stateMutability": "view",
                    "type": "function"
                }]
            )

            for fee in fee_tiers:
                try:
                    pool_address = factory_contract.functions.getPool(
                        self.WETH_ADDRESS,
                        token_address,
                        fee
                    ).call()

                    if pool_address != "0x0000000000000000000000000000000000000000":
                        # Vérifier la liquidité
                        pool_contract = self.w3.eth.contract(
                            address=pool_address,
                            abi=[{
                                "inputs": [],
                                "name": "liquidity",
                                "outputs": [{"internalType": "uint128", "name": "", "type": "uint128"}],
                                "stateMutability": "view",
                                "type": "function"
                            }]
                        )
                        liquidity = pool_contract.functions.liquidity().call()
                        
                        if liquidity > best_liquidity:
                            best_liquidity = liquidity
                            best_pool = (fee, pool_address)
                except Exception as e:
                    print(f"Erreur lors de la vérification du pool {fee/10000}%: {str(e)}")
                    continue

            if not best_pool:
                raise Exception("Aucun pool avec liquidité trouvé")

            # 3. Construction des paramètres du swap
            params = {
                'tokenIn': self.WETH_ADDRESS,
                'tokenOut': token_address,
                'fee': best_pool[0],
                'recipient': self.address,
                'deadline': int(time.time()) + 300,
                'amountIn': amount_in_wei,
                'amountOutMinimum': min_out,
                'sqrtPriceLimitX96': 0
            }

            # 4. Simulation de la transaction
            try:
                self.router_contract.functions.exactInputSingle(params).call({
                    'from': self.address,
                    'value': amount_in_wei
                })
            except Exception as e:
                raise Exception(f"Échec de la simulation du swap: {str(e)}")

            # 5. Construction et envoi de la transaction
            tx = self.router_contract.functions.exactInputSingle(params).build_transaction({
                'from': self.address,
                'value': amount_in_wei,
                'gas': 500000,  # Gas limit plus élevé pour plus de sécurité
                'maxFeePerGas': int(self.w3.eth.get_block('latest').baseFeePerGas * 2.5 + self.w3.eth.max_priority_fee),
                'maxPriorityFeePerGas': self.w3.eth.max_priority_fee,
                'nonce': self.w3.eth.get_transaction_count(self.address),
                'chainId': 8453  # Base Mainnet
            })

            # 6. Signature et envoi
            signed_tx = self.w3.eth.account.sign_transaction(tx, self.account.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            # 7. Attente de la confirmation avec retry
            max_retries = 3
            for i in range(max_retries):
                try:
                    receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
                    if receipt['status'] == 1:
                        return tx_hash.hex()
                    else:
                        raise Exception(f"Transaction échouée. Voir https://basescan.org/tx/{tx_hash.hex()}")
                except Exception as e:
                    if i == max_retries - 1:
                        raise Exception(f"Échec de la confirmation après {max_retries} tentatives: {str(e)}")
                    time.sleep(2 ** i)  # Backoff exponentiel

        except Exception as e:
            print(f"Erreur détaillée lors du swap ETH -> token: {str(e)}")
            return str(e)

    def check_pool_exists(self, token_address, amount_in_wei=10**15):
        """
        Vérifie si une pool Uniswap V3 WETH/token existe et a de la liquidité.
        Retourne True si la pool existe et amountOut > 0, False sinon.
        """
        try:
            quoter_abi = [{
                "inputs": [
                    {"internalType": "address", "name": "tokenIn", "type": "address"},
                    {"internalType": "address", "name": "tokenOut", "type": "address"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"},
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}
                ],
                "name": "quoteExactInputSingle",
                "outputs": [
                    {"internalType": "uint256", "name": "amountOut", "type": "uint256"}
                ],
                "stateMutability": "view",
                "type": "function"
            }]
            quoter = self.w3.eth.contract(address=self.UNISWAP_V3_QUOTER, abi=quoter_abi)
            amount_out = quoter.functions.quoteExactInputSingle(
                self.WETH_ADDRESS,
                token_address,
                3000,
                amount_in_wei,
                0
            ).call()
            return amount_out > 0
        except Exception as e:
            print(f"[POOL CHECK] Erreur: {str(e)}")
            return False

def buy_token(update: Update, context: CallbackContext):
    """Gère la commande /buy pour acheter un token"""
    try:
        # Vérification des arguments
        if len(context.args) != 2:
            update.message.reply_text(
                "❌ Format incorrect\n"
                "Utilisation : /buy <adresse_token> <montant_eth>\n"
                "Exemple : /buy 0x123... 0.1"
            )
            return

        # Récupération des arguments
        token_address = context.args[0]
        try:
            amount_eth = float(context.args[1])
        except ValueError:
            update.message.reply_text("❌ Le montant doit être un nombre valide")
            return

        # Vérification de l'adresse du token
        if not Web3.is_address(token_address):
            update.message.reply_text("❌ Adresse de token invalide")
            return

        # Conversion en wei
        amount_wei = Web3.to_wei(amount_eth, 'ether')

        # Création de l'instance ClankerSniper
        sniper = ClankerSniper(
            rpc_url="https://mainnet.base.org",
            private_key=os.getenv("PRIVATE_KEY")
        )

        # Vérification du solde
        balance = sniper.w3.eth.get_balance(sniper.address)
        balance_eth = Web3.from_wei(balance, 'ether')
        
        update.message.reply_text(
            f"💰 Solde actuel : {balance_eth:.4f} ETH\n"
            f"🎯 Montant à acheter : {amount_eth:.4f} ETH"
        )

        if balance < amount_wei:
            update.message.reply_text("❌ Solde insuffisant")
            return

        # Vérification de la liquidité
        update.message.reply_text("🔍 Vérification de la liquidité...")
        if not sniper.check_pool_exists(token_address):
            update.message.reply_text("❌ Pas de pool avec liquidité trouvée")
            return

        # Exécution du swap
        update.message.reply_text("🔄 Exécution du swap...")
        tx_hash = sniper.swap_eth_for_token(token_address, amount_wei)

        if tx_hash:
            update.message.reply_text(
                f"✅ Swap exécuté avec succès !\n"
                f"🔗 Transaction : https://basescan.org/tx/{tx_hash}"
            )
        else:
            update.message.reply_text("❌ Échec du swap")

    except Exception as e:
        update.message.reply_text(f"❌ Erreur : {str(e)}") 