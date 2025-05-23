// buy.js
require('dotenv').config();
const { ethers } = require("ethers");

// Paramètres Uniswap V3 sur Base
const ROUTER_ADDRESS = "0x2626664c2603336E57B271c5C0b26F421741e481";
const WETH_ADDRESS = "0x4200000000000000000000000000000000000006";
const ROUTER_ABI = [
  {
    "inputs": [
      {
        "components": [
          { "internalType": "address", "name": "tokenIn", "type": "address" },
          { "internalType": "address", "name": "tokenOut", "type": "address" },
          { "internalType": "uint24", "name": "fee", "type": "uint24" },
          { "internalType": "address", "name": "recipient", "type": "address" },
          { "internalType": "uint256", "name": "deadline", "type": "uint256" },
          { "internalType": "uint256", "name": "amountIn", "type": "uint256" },
          { "internalType": "uint256", "name": "amountOutMinimum", "type": "uint256" },
          { "internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160" }
        ],
        "internalType": "struct ISwapRouter.ExactInputSingleParams",
        "name": "params",
        "type": "tuple"
      }
    ],
    "name": "exactInputSingle",
    "outputs": [
      { "internalType": "uint256", "name": "amountOut", "type": "uint256" }
    ],
    "stateMutability": "payable",
    "type": "function"
  }
];

const FACTORY_ADDRESS = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD";
const FACTORY_ABI = [
  {
    "inputs": [
      { "internalType": "address", "name": "tokenA", "type": "address" },
      { "internalType": "address", "name": "tokenB", "type": "address" },
      { "internalType": "uint24", "name": "fee", "type": "uint24" }
    ],
    "name": "getPool",
    "outputs": [{ "internalType": "address", "name": "", "type": "address" }],
    "stateMutability": "view",
    "type": "function"
  }
];

const POOL_ABI = [
  {
    "inputs": [],
    "name": "liquidity",
    "outputs": [{ "internalType": "uint128", "name": "", "type": "uint128" }],
    "stateMutability": "view",
    "type": "function"
  }
];

// Récupère les arguments
const [,, poolAddressRaw, amountEth] = process.argv;

// Correction automatique de l'adresse en minuscules
const poolAddress = poolAddressRaw ? poolAddressRaw.toLowerCase() : null;

if (!poolAddress || !amountEth) {
  console.error("Usage: node buy.js <pool_address> <amount_eth>");
  process.exit(1);
}

const PRIVATE_KEY = process.env.PRIVATE_KEY;
const RPC_URL = process.env.RPC_URL || "https://mainnet.base.org";

if (!PRIVATE_KEY) {
  console.error("PRIVATE_KEY manquante dans les variables d'environnement.");
  process.exit(1);
}

const POOL_ABI_EXTENDED = [
  ...POOL_ABI,
  { "inputs": [], "name": "token0", "outputs": [{ "internalType": "address", "name": "", "type": "address" }], "stateMutability": "view", "type": "function" },
  { "inputs": [], "name": "token1", "outputs": [{ "internalType": "address", "name": "", "type": "address" }], "stateMutability": "view", "type": "function" }
];

async function main() {
  const provider = new ethers.JsonRpcProvider(RPC_URL);
  const wallet = new ethers.Wallet(PRIVATE_KEY, provider);
  const router = new ethers.Contract(ROUTER_ADDRESS, ROUTER_ABI, wallet);

  // Solde ETH
  const balance = await provider.getBalance(wallet.address);
  console.log("[INFO] Solde ETH:", ethers.formatEther(balance), "ETH");

  const amountIn = ethers.parseEther(amountEth);
  if (balance < amountIn) {
    console.error("[ERROR] Solde ETH insuffisant");
    process.exit(2);
  }

  // Vérification de la liquidité et détection du sens
  const pool = new ethers.Contract(poolAddress, POOL_ABI_EXTENDED, provider);
  const liquidity = await pool.liquidity();
  const token0 = await pool.token0();
  const token1 = await pool.token1();
  console.log(`[INFO] Pool: ${poolAddress}`);
  console.log(`[INFO] token0: ${token0}`);
  console.log(`[INFO] token1: ${token1}`);
  console.log(`[INFO] Liquidité de la pool: ${liquidity.toString()}`);

  if (liquidity === 0n) {
    console.error("[ERROR] Pool n'a pas de liquidité");
    process.exit(2);
  }

  let tokenOut;
  if (token0.toLowerCase() === WETH_ADDRESS.toLowerCase()) {
    tokenOut = token1;
    console.log(`[INFO] Swap ETH -> token1 (tokenOut): ${tokenOut}`);
  } else if (token1.toLowerCase() === WETH_ADDRESS.toLowerCase()) {
    tokenOut = token0;
    console.log(`[INFO] Swap ETH -> token0 (tokenOut): ${tokenOut}`);
  } else {
    console.error("[ERROR] Aucun WETH dans la pool !");
    process.exit(2);
  }

  // Solde du token cible
  const ERC20_ABI = ["function balanceOf(address) view returns (uint256)"];
  const tokenContract = new ethers.Contract(tokenOut, ERC20_ABI, provider);
  const tokenBalance = await tokenContract.balanceOf(wallet.address);
  console.log(`[INFO] Solde du token cible (${tokenOut}): ${ethers.formatUnits(tokenBalance, 18)}`);

  const deadline = Math.floor(Date.now() / 1000) + 300;
  console.log(`[INFO] Deadline: ${new Date(deadline * 1000).toISOString()}`);

  const params = {
    tokenIn: WETH_ADDRESS,
    tokenOut: tokenOut,
    fee: 10000,
    recipient: wallet.address,
    deadline: deadline,
    amountIn: amountIn,
    amountOutMinimum: 0,
    sqrtPriceLimitX96: 0
  };

  console.log("[INFO] Paramètres de la transaction:", JSON.stringify({
    router: ROUTER_ADDRESS,
    pool: poolAddress,
    tokenIn: params.tokenIn,
    tokenOut: params.tokenOut,
    fee: params.fee,
    recipient: params.recipient,
    deadline: params.deadline,
    amountIn: params.amountIn.toString(),
    amountOutMinimum: params.amountOutMinimum,
    sqrtPriceLimitX96: params.sqrtPriceLimitX96
  }, null, 2));

  try {
    // Estimation du gas
    const gasEstimate = await router.exactInputSingle.estimateGas(
      params,
      { value: amountIn }
    );
    console.log("[INFO] Estimation gas:", gasEstimate.toString());

    const tx = await router.exactInputSingle(
      params,
      { 
        value: amountIn, 
        gasLimit: Math.floor(gasEstimate * 1.2) // +20% de marge
      }
    );
    console.log("SUCCESS", tx.hash);
  } catch (e) {
    console.error("[ERROR] Swap failed:");
    console.error("[ERROR] Reason:", e.reason || e.message || e);
    if (e.transaction) {
      console.error("[ERROR] Transaction:", JSON.stringify(e.transaction, null, 2));
    }
    if (e.data) {
      console.error("[ERROR] Data:", e.data);
    }
    process.exit(2);
  }
}

main(); 