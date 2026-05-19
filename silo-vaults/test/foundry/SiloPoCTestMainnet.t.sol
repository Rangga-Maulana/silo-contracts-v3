// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "forge-std/console.sol";
import {IERC20} from "openzeppelin5/token/ERC20/IERC20.sol";
import {IERC4626} from "openzeppelin5/interfaces/IERC4626.sol";

// Interface untuk PublicAllocator
interface IPublicAllocator {
    struct Withdrawal {
        IERC4626 market;
        uint128 amount;
    }
    function reallocateTo(address vault, Withdrawal[] calldata withdrawals, IERC4626 supplyMarket) external;
}

contract SiloXDCMainnetMockStyleTest is Test {
    string XDC_RPC_URL = "https://erpc.xinfin.network/"; 
    
    address constant USDC = 0xfA2958CB79b0491CC627c1557F441eF849Ca8eb1;
    address constant SILO_VAULT = 0x06083Db34F1E915FA5cd4e2A198f3680E3CE9c60; 
    address constant EXTERNAL_MARKET = 0xB38658B163E364DfFFDBC895f1b5d658d5e6C439; 
    address constant SOURCE_MARKET = 0xd1ed56Ed95c02634D9e2385A04cd5b97078dd932; 
    
    // Address dari PublicAllocator (Asumsi: sender dari hex tx sebelumnya)
    address constant ALLOCATOR = 0x8e65743e23Ed13f593E7d4eb7ED3ddE1E1cB9bBf; 

    function setUp() public {
        uint256 forkId = vm.createFork(XDC_RPC_URL);
        vm.selectFork(forkId);
    }

    function test_MainnetWithdrawalSlippage() public {
        uint256 vaultTVLBefore = IERC4626(SILO_VAULT).totalAssets();
        console.log("Vault TVL Asli :", vaultTVLBefore);

        // 1. DI POC MOCK, ANDA MENGHANCURKAN HARGA MARKET DI SINI.
        // Di Mainnet, kita TIDAK BISA menghancurkan harga External Market 
        // karena tidak ada fungsi `simulateFlashLoanCrash`. 
        // Market akan selalu mereturn aset dengan rasio yang benar.
        
        console.log("\n[!] Mencoba mengeksekusi penarikan via PublicAllocator...");

        // 2. EKSEKUSI VAULT: Allocator menarik uang (Seperti di PoC Mock)
        vm.startPrank(ALLOCATOR);
        
        IPublicAllocator.Withdrawal[] memory withdrawals = new IPublicAllocator.Withdrawal[](1);
        withdrawals[0] = IPublicAllocator.Withdrawal({
            market: IERC4626(EXTERNAL_MARKET),
            amount: 10_000 * 1e6 // Tarik 10,000 USDC
        });
        
        // Panggil PublicAllocator untuk menarik dari External dan setor ke Source
        IPublicAllocator(ALLOCATOR).reallocateTo(
            SILO_VAULT, 
            withdrawals, 
            IERC4626(SOURCE_MARKET)
        );
        vm.stopPrank();

        // 3. CEK KERUSAKAN VAULT
        uint256 vaultTVLAfter = IERC4626(SILO_VAULT).totalAssets();
        console.log("Vault TVL Setelah Penarikan :", vaultTVLAfter);

        if (vaultTVLAfter < vaultTVLBefore) {
            console.log("\n[+] BINGO! Vault Rugi!");
        } else {
            console.log("\n[-] GAGAL RUGI. Karena harga market tidak bisa dikurangi secara paksa (seperti simulateFlashLoanCrash), penarikan berjalan dengan rasio wajar dan Vault tidak mengalami slippage.");
        }
    }
}
