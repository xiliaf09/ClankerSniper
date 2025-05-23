# ClankerSniper Bot

Un bot Telegram pour sniping automatique de tokens Clanker sur Base.

## Fonctionnalités

- Surveillance des nouveaux tokens Clanker par FID
- Achat automatique via Uniswap V3
- Gestion des snipe via commandes Telegram
- Configuration du montant et des frais de gas
- Interface utilisateur intuitive

## Installation

1. Clonez le repository :
```bash
git clone https://github.com/xiliaf09/ClankerSniper.git
cd ClankerSniper
```

2. Installez les dépendances :
```bash
pip install -r requirements.txt
```

3. Créez un fichier `.env` avec les variables suivantes :
```
TELEGRAM_TOKEN=your_telegram_bot_token
PRIVATE_KEY=your_wallet_private_key
QUICKNODE_RPC=https://damp-necessary-frog.base-mainnet.quiknode.pro/d60be1af9ee2c8dade56c2372d1b4b166205e14e/
```

## Utilisation

1. Démarrez le bot :
```bash
python main.py
```

2. Commandes disponibles :
- `/start` - Démarrer le bot
- `/help` - Afficher l'aide
- `/snipe <FID> <montant_WETH>` - Configurer un snipe
- `/list` - Lister les snipe actifs
- `/remove <FID>` - Supprimer un snipe
- `/update <FID> <nouveau_montant>` - Mettre à jour un snipe

## Déploiement

Le bot peut être déployé sur Railway. Assurez-vous de configurer les variables d'environnement dans l'interface Railway.

## Sécurité

- La clé privée du wallet est stockée de manière sécurisée dans les variables d'environnement
- Les transactions sont signées localement
- Les montants minimums de sortie sont configurés pour éviter le slippage

## Support

Pour toute question ou problème, veuillez ouvrir une issue sur GitHub. 